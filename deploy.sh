#!/bin/bash
cd "$HOME/jarvis" || exit 1
exec >> "$HOME/jarvis/deploy.log" 2>&1
echo "=== deploy $(date "+%F %T") ==="
OLD=$(git rev-parse HEAD 2>/dev/null)
git fetch -q origin main && git reset --hard -q origin/main
NEW=$(git rev-parse HEAD 2>/dev/null)
VN=$(sed -n "s/.*versionName \"\([^\"]*\)\".*/\1/p" frontend/android/app/build.gradle | head -1)
[ -n "$VN" ] && printf "{\"version\":\"%s\"}\n" "$VN" > /var/www/jarvis/version.json
if [ "$OLD" = "$NEW" ]; then echo "sin cambios ($NEW)"; exit 0; fi
CH=$(git diff --name-only "$OLD" "$NEW")
echo "cambios:"; echo "$CH" | sed "s/^/  /"
if echo "$CH" | grep -q "^backend/"; then pm2 restart jarvis-backend >/dev/null 2>&1 && echo "-> backend reiniciado"; fi
if echo "$CH" | grep -qE "^frontend/(src/|index.html|package|vite|tailwind|postcss)"; then ( cd frontend && NODE_ENV=development npx vite build >/dev/null 2>&1 && cp -r dist/* /var/www/jarvis/ ) && echo "-> web desplegada"; fi
if echo "$CH" | grep -qE "^frontend/android/app/src/|^frontend/android/app/build.gradle|^frontend/android/variables.gradle"; then echo "-> cambio NATIVO, recompilando APK..."; ( cd frontend/android && docker run --rm -u 0:0 -v ~/jarvis/frontend:/project -v ~/jarvis/android-keys:/keys -v ~/.gradle-jarvis:/root/.gradle -w /project/android mobiledevops/android-sdk-image:34.0.0-jdk17 ./gradlew assembleRelease --no-daemon >/dev/null 2>&1 && cp app/build/outputs/apk/release/app-release.apk /var/www/jarvis/jarvis.apk ) && echo "-> APK actualizada"; fi
echo "=== fin ==="
