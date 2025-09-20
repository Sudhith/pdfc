Quick deploy checklist
- Ensure requirements.txt contains gunicorn (e.g., "gunicorn>=20.0.0") and all other libs.
- Railway will use your Dockerfile if you push one. Confirm the Dockerfile changes are committed.
- You set PORT=5000 in Railway — OK. Container will bind to that port via start.sh.
- Test locally: build and run
  - docker build -t pdfc .
  - docker run -e PORT=5000 -p 5000:5000 pdfc
- If errors appear in Railway logs, paste the failing log lines and I can pinpoint fixes.
