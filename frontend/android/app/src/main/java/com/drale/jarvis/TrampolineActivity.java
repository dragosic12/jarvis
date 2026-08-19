package com.drale.jarvis;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.WindowManager;

/**
 * Actividad invisible que puede mostrarse sobre la pantalla bloqueada,
 * encender la pantalla y lanzar el deep link. Necesaria porque Android 10+
 * bloquea abrir otras apps directamente desde segundo plano.
 */
public class TrampolineActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
            KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
            if (km != null) {
                km.requestDismissKeyguard(this, null);
            }
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                    | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                    | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD);
        }

        String url = getIntent().getStringExtra("url");
        if (url != null) {
            try {
                if ("camera".equals(url)) {
                    Intent cam = new Intent(android.provider.MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA);
                    cam.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(cam);
                } else if (url.startsWith("jarvis-alarm://")) {
                    String[] hm = url.substring("jarvis-alarm://".length()).split(":");
                    Intent al = new Intent(android.provider.AlarmClock.ACTION_SET_ALARM);
                    al.putExtra(android.provider.AlarmClock.EXTRA_HOUR, Integer.parseInt(hm[0]));
                    al.putExtra(android.provider.AlarmClock.EXTRA_MINUTES, hm.length > 1 ? Integer.parseInt(hm[1]) : 0);
                    al.putExtra(android.provider.AlarmClock.EXTRA_SKIP_UI, false);
                    al.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(al);
                } else if (url.startsWith("jarvis-timer://")) {
                    int secs = Integer.parseInt(url.substring("jarvis-timer://".length()));
                    Intent ti = new Intent(android.provider.AlarmClock.ACTION_SET_TIMER);
                    ti.putExtra(android.provider.AlarmClock.EXTRA_LENGTH, secs);
                    ti.putExtra(android.provider.AlarmClock.EXTRA_SKIP_UI, true);
                    ti.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(ti);
                } else if (url.startsWith("intent:")) {
                    // Deep link Android: respeta package + S.browser_fallback_url
                    Intent view = Intent.parseUri(url, Intent.URI_INTENT_SCHEME);
                    view.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    try {
                        startActivity(view);
                    } catch (Exception notFound) {
                        String fb = view.getStringExtra("browser_fallback_url");
                        if (fb != null) {
                            Intent web = new Intent(Intent.ACTION_VIEW, Uri.parse(fb));
                            web.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                            startActivity(web);
                        }
                    }
                } else {
                    Intent view = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    view.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(view);
                }
            } catch (Exception ignored) {
            }
        }
        finish();
    }
}
