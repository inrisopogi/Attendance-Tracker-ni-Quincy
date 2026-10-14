# Attendance Tracker (Python + Firebase)

Flask app, Firestore database, mobile-friendly UI you can add to your phone's home screen.

## 1. Create the Firebase database (about 5 minutes, needs your Google account)
1. Go to https://console.firebase.google.com and click **Create a project**.
2. **Build > Firestore Database > Create database**. Choose a location near you
   (e.g. `asia-southeast1`) and **Production mode**. (Keep the default locked rules;
   the server uses an admin key, so the browser never touches the database directly.)
3. **Project settings (gear) > Service accounts > Generate new private key**.
   Save the file as `serviceAccountKey.json` in this folder. Never share or commit it.

## 2. Try it on your computer
```
pip install -r requirements.txt
USERS=juan:pass1,maria:pass2 python app.py      # Windows Command Prompt: set USERS=juan:pass1,maria:pass2
```
Open http://localhost:8080 and log in with one of the usernames and passwords. Add students one by one, or use **Import spreadsheet** with the Attendance Template.

## 3. Deploy so your phone can use it

### Option A: Render (free, no billing account)
1. Put this folder in a GitHub repo (`.gitignore` already excludes the key).
2. render.com > **New > Web Service** > pick the repo, Runtime **Docker**.
3. Environment variables:
   - `APP_PASSWORD` = your password
   - `FIREBASE_CREDENTIALS` = the full contents of `serviceAccountKey.json`
4. Deploy. You get an `https://...onrender.com` URL. (Free instances sleep when idle; the first load takes ~30 s.)

### Option B: Google Cloud Run (same Google project as Firebase)
```
gcloud run deploy attendance --source . --region asia-southeast1 \
  --allow-unauthenticated --set-env-vars APP_PASSWORD=choose-a-password
```
No key file is needed: Cloud Run uses its own service account, which must have the
**Cloud Datastore User** role on the project. Cloud Run requires billing to be enabled
(small usage stays within the free quota).

## 4. Put it on your phone
Open the URL in Chrome (Android) or Safari (iPhone), then **Add to Home Screen**.
It opens full-screen like an app.

## Notes
- Data: `students/{id}` and `attendance/{date}` documents in Firestore.
- Anyone with the URL and password can edit records, so use a strong password.
- A real Play Store / App Store app would need a separate native or Flutter build.

## Accounts: each person logs in with their own username and password
Set one environment variable, `USERS`, as `username:password` pairs separated by commas:

    USERS=juan:Pass1word,maria:Another2Pass,teacher.ana:Third3Pass

- On Render: Environment > add `USERS` (it replaces `APP_PASSWORD`), then save; Render redeploys.
- Usernames: letters, numbers, `.`, `_`, `-` only (not case-sensitive). Passwords must not contain `,` or `:`.
- Each login gets its own private students and attendance. People cannot see each other's data.
- To add, remove or change a person, edit `USERS` and save. Removing a person blocks their login but keeps their data in Firebase.
- If `USERS` is not set but `APP_PASSWORD` is, everyone shares one password and one set of data.
