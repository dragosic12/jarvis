package com.drale.jarvis;

import android.app.Notification;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import java.util.HashSet;
import java.util.Set;

/**
 * Lee en alto los mensajes entrantes (WhatsApp, Telegram, SMS) cuando el modo
 * coche esta activo. Requiere que el usuario conceda "Acceso a notificaciones"
 * a Jarvis. Fuera del modo coche no hace nada.
 */
public class JarvisNotifService extends NotificationListenerService {

    private static final Set<String> MSG_APPS = new HashSet<>();
    static {
        MSG_APPS.add("com.whatsapp");
        MSG_APPS.add("com.whatsapp.w4b");                 // WhatsApp Business
        MSG_APPS.add("org.telegram.messenger");
        MSG_APPS.add("com.google.android.apps.messaging"); // SMS
    }

    private String lastKey = "";
    private long lastAt = 0;

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            if (!ListeningService.isCarMode()) return;
            if (sbn == null) return;
            String pkg = sbn.getPackageName();
            if (pkg == null || !MSG_APPS.contains(pkg)) return;

            Notification n = sbn.getNotification();
            if (n == null) return;
            // Ignora resumenes de grupo y notificaciones en curso (llamadas, "escribiendo...")
            if ((n.flags & Notification.FLAG_GROUP_SUMMARY) != 0) return;
            if ((n.flags & Notification.FLAG_ONGOING_EVENT) != 0) return;

            Bundle ex = n.extras;
            if (ex == null) return;
            CharSequence titleCs = ex.getCharSequence(Notification.EXTRA_TITLE);
            CharSequence textCs = ex.getCharSequence(Notification.EXTRA_TEXT);
            String title = titleCs != null ? titleCs.toString().trim() : "";
            String text = textCs != null ? textCs.toString().trim() : "";
            if (text.isEmpty()) return;
            // Filtra los resumenes inutiles ("3 mensajes", "escribiendo...")
            if (text.matches("(?i).*\\b(\\d+ mensajes?|escribiendo|typing)\\b.*")) return;

            String key = pkg + "|" + title + "|" + text;
            long now = System.currentTimeMillis();
            if (key.equals(lastKey) && now - lastAt < 8000) return;  // dedup
            lastKey = key;
            lastAt = now;

            String said = title.isEmpty() ? ("Mensaje: " + text)
                                          : ("Mensaje de " + title + ": " + text);
            ListeningService.carAnnounce(said);
        } catch (Exception ignored) {}
    }
}
