pipeline {
  agent any
  environment { DEPLOY_DIR = '/opt/nesthost' }   // contains your real .env (never commit it)
  options { timestamps(); disableConcurrentBuilds() }
  stages {
    stage('Checkout') { steps { checkout scm } }
    stage('Unit tests') {
      steps { sh '''
        python3 -m venv .venv
        . .venv/bin/activate
        pip install -q -r requirements.txt
        python -W ignore -m unittest discover -s tests -v
      ''' }
    }
    stage('Deploy') {
      steps { sh '''
        test -f "$DEPLOY_DIR/.env" || { echo "Create $DEPLOY_DIR/.env first (copy .env.example)"; exit 1; }
        rsync -a --delete --exclude .git --exclude .venv --exclude .env ./ "$DEPLOY_DIR/"
        cd "$DEPLOY_DIR"
        docker compose up -d --build
        for i in $(seq 1 30); do
          docker compose exec -T app python -c "import urllib.request as u;print(u.urlopen('http://localhost:8000/healthz').read())" && exit 0
          sleep 3
        done
        docker compose logs --tail 50 app; exit 1
      ''' }
    }
  }
}
