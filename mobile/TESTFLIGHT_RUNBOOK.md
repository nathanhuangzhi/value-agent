# TestFlight runbook

Step-by-step. Most prep work is already done — what's left below
requires either your Expo account credentials or your Apple
Developer account (which is pending approval). Run in order.

## Status as of this writing

Done ✅
- App icon + splash + favicon assets generated and committed
- `app.json`: version 1.0.0, ios.buildNumber=1, encryption-exempt
- `eas.json` written with dev / preview / production profiles
- Privacy policy live at value-agent-reports.vercel.app/privacy.html
- App Store metadata drafted in `APP_STORE_METADATA.md`
- `eas-cli` installed globally

Waiting on you ⏳
- Apple Developer Program membership (pending Apple)
- Expo account (free, at expo.dev)
- Final UI sanity-check in Expo Go

## Step-by-step

### 1. Create Expo account (1 min, no Apple needed)

Sign up at https://expo.dev/signup with your email. Free tier
includes ~30 iOS builds/month — plenty.

### 2. Link the local project to Expo (no Apple needed)

```bash
cd /home/hz911224/projects/value-agent/mobile
eas login                    # prompts for Expo email + password
eas init                     # writes extra.eas.projectId into app.json
```

After `eas init`, your `app.json` gets a `extra.eas.projectId` line.
**Commit that diff.**

### 3. Smoke-test the production build env (no Apple needed)

The eas.json already has `EXPO_PUBLIC_API_URL` baked into each profile.
You can verify it'll be picked up by running:

```bash
eas env:list --environment production
```

If you ever change the API URL later, edit `eas.json` directly, or
push via `eas env:create`.

### 4. (Wait) Apple Developer approval lands

You'll get an email. Then continue.

### 5. Run the production build (~15-20 min in EAS cloud)

```bash
eas build --platform ios --profile production
```

EAS will ask interactive prompts:
- "Generate Apple Distribution Certificate?" → **Yes**
- "Generate Apple Provisioning Profile?" → **Yes**
- "Apple ID email?" → enter the Apple ID tied to your Developer account
- "App-specific password?" → generate one at appleid.apple.com
  → Sign-In and Security → App-Specific Passwords → label it
  "EAS Build" → paste the 19-char password EAS shows

(You only do these prompts once; EAS caches credentials for future
builds.)

EAS uploads your code to its cloud builder. Watch progress at the
URL it prints. When done you get a `.ipa` download link.

### 6. Submit to App Store Connect

```bash
eas submit --platform ios --latest
```

Prompts:
- "App Store Connect app?" → **Create new** (EAS makes it for you
  using your bundle ID)
- "ASC App Name?" → `Valueland`
- "Language?" → `en-US`
- "SKU?" → any unique string, e.g. `valueland-ios-001`

EAS pushes the build to App Store Connect (~5 min upload + ~10 min
Apple processing).

### 7. Configure App Store Connect for TestFlight

Go to https://appstoreconnect.apple.com → My Apps → Valueland.

Initial chores Apple wants done before the build is testable:

1. **TestFlight tab → wait for the build to flip from "Processing"
   to "Ready to Submit"** (~10 min).

2. **Click the build → "Test Information"**:
   - Paste the description from `APP_STORE_METADATA.md`'s
     "Description" section (short version is fine).
   - Beta App Description: same text.
   - Beta App Feedback Email: your Gmail.

3. **Encryption compliance**: should auto-resolve because
   `ITSAppUsesNonExemptEncryption: false` is already in our
   Info.plist. If not, click the orange warning → "Does your app
   use encryption?" → **No** → save.

### 8. Add yourself as an internal tester

In the TestFlight tab:

1. Click **+** next to "Internal Testing" → name the group
   "Personal", click Create.
2. **+** next to "Testers" → add your Apple ID email.
3. Tick the build you want them to access.

### 9. Install on your iPhone

1. Install **TestFlight** app from the App Store (if not already).
2. Sign into TestFlight with the same Apple ID you added as a
   tester.
3. Open the invite email Apple just sent you, tap "View in
   TestFlight" → Install.

Valueland appears on your home screen with the green V icon.

### 10. Shipping subsequent builds

After your first successful build/submit, future updates are:

```bash
# Edit code, test in Expo Go.
# When ready to push to TestFlight:
eas build --platform ios --profile production
eas submit --platform ios --latest
```

`autoIncrement: true` in eas.json bumps the buildNumber for you.

Builds appear in TestFlight ~15 min after `eas submit` returns.
TestFlight on your phone shows an "Update" button.

## Common gotchas

- **TestFlight builds expire after 90 days.** Push a fresh build at
  least every 3 months to keep using it.

- **EXPO_PUBLIC_API_URL must be set at build time, not runtime.**
  Our `eas.json` bakes it in. If you ever switch CDNs, edit
  `eas.json` and re-build.

- **Bundle ID is permanent.** Do not change
  `com.nathanhuang.valueland` after the first submit — App Store
  Connect locks it to that identifier.

- **Don't bump version manually unless you mean to.** EAS
  auto-increments buildNumber, but `version` (1.0.0) stays until you
  manually bump it. Apple won't let you re-submit the same
  version+build pair.

- **First build often fails because of Apple credential prompts.**
  Just re-run `eas build` and answer them this time — credentials
  cache after the first run.
