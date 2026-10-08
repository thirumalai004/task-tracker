pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '15'))
    }

    parameters {
        choice(name: 'ENVIRONMENT', choices: ['dev', 'prod'], description: 'Where to deploy')
        password(name: 'DB_PASSWORD', defaultValue: 'change-me', description: 'Database password for the chosen environment')
    }

    environment {
        IMAGE  = 'task-tracker'
        NET    = "tt-net-${BUILD_NUMBER}"
        TESTDB = "tt-testdb-${BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                // Fail fast: check the parameters before doing any Docker work.
                script {
                    if (!params.DB_PASSWORD?.trim()) {
                        error 'DB_PASSWORD must not be empty'
                    }
                }
                checkout scm
                sh 'docker version --format "Docker server {{.Server.Version}}"'
            }
        }

        stage('Build and Unit Test') {
            steps {
                // The unit tests run inside this build; a failing test stops the pipeline.
                sh 'docker build --target test -t "$IMAGE:test" .'
                sh 'docker build -t "$IMAGE:$BUILD_NUMBER" .'
            }
        }

        stage('Start Test DB') {
            steps {
                sh '''
                    docker network create "$NET"
                    docker run -d --name "$TESTDB" --network "$NET" \
                        -e POSTGRES_PASSWORD=test -e POSTGRES_DB=tasks postgres:16
                    i=0
                    until docker exec "$TESTDB" pg_isready -h 127.0.0.1 -U postgres; do
                        i=$((i + 1))
                        if [ "$i" -ge 30 ]; then
                            echo "Test database did not start"
                            docker logs "$TESTDB"
                            exit 1
                        fi
                        sleep 2
                    done
                '''
            }
        }

        stage('Integration Test') {
            steps {
                sh '''
                    docker run --rm --network "$NET" \
                        -e DB_HOST="$TESTDB" -e DB_PASSWORD=test -e APP_ENV=test \
                        "$IMAGE:$BUILD_NUMBER" python integration_test.py
                '''
            }
        }

        stage('Tag') {
            steps {
                // "latest" only moves after every test has passed.
                sh 'docker tag "$IMAGE:$BUILD_NUMBER" "$IMAGE:latest"'
                sh 'docker images "$IMAGE"'
            }
        }

        stage('Deploy') {
            steps {
                // ENVIRONMENT and DB_PASSWORD reach the script as environment variables.
                sh 'sh deploy.sh "$ENVIRONMENT" "$BUILD_NUMBER"'
            }
        }

        stage('Health Check') {
            steps {
                sh '''
                    APP="tt-$ENVIRONMENT-app"
                    docker exec "$APP" python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3).read().decode())"
                    docker ps --filter "name=tt-$ENVIRONMENT" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
                '''
            }
        }
    }

    post {
        always {
            // Runs after success AND failure: nothing is left behind.
            sh '''
                docker rm -f "$TESTDB" >/dev/null 2>&1 || true
                docker network rm "$NET" >/dev/null 2>&1 || true
            '''
        }
        success {
            echo "Deployed ${IMAGE}:${BUILD_NUMBER} to ${params.ENVIRONMENT}"
        }
        failure {
            echo 'Build failed. Check the first stage that turned red; deploy.sh logs a rollback if one happened.'
        }
    }
}
