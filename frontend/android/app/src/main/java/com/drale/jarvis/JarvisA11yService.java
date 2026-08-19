package com.drale.jarvis;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Path;
import android.util.DisplayMetrics;
import android.view.accessibility.AccessibilityEvent;

/**
 * Servicio de Accesibilidad: la UNICA via para ejecutar acciones del sistema
 * (atras, inicio, recientes, notificaciones) desde una app. Lo dispara
 * FaceGestureService cuando detecta un gesto. El usuario lo activa una vez en
 * Ajustes -> Accesibilidad -> Jarvis Gestos.
 */
public class JarvisA11yService extends AccessibilityService {

    private static JarvisA11yService instance;
    private static volatile String curPkg = "";

    @Override
    protected void onServiceConnected() {
        instance = this;
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // Rastrea la app en primer plano (para gestos que cambian segun la app)
        if (event != null && event.getEventType() == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            CharSequence p = event.getPackageName();
            if (p != null) {
                String s = p.toString();
                if (!s.contains("systemui") && !s.contains("inputmethod") && !s.equals("android")) {
                    curPkg = s;
                }
            }
        }
    }

    public static String currentPackage() { return curPkg; }

    /** Swipe vertical en el centro (scroll). up=dedo hacia arriba (avanza/siguiente). */
    public static void swipe(boolean up) {
        if (instance == null) return;
        try {
            DisplayMetrics dm = instance.getResources().getDisplayMetrics();
            float x = dm.widthPixels / 2f;
            float y1 = up ? dm.heightPixels * 0.72f : dm.heightPixels * 0.32f;
            float y2 = up ? dm.heightPixels * 0.30f : dm.heightPixels * 0.74f;
            Path path = new Path();
            path.moveTo(x, y1);
            path.lineTo(x, y2);
            GestureDescription gd = new GestureDescription.Builder()
                    .addStroke(new GestureDescription.StrokeDescription(path, 0, 200))
                    .build();
            instance.dispatchGesture(gd, null, null);
        } catch (Exception ignored) {}
    }

    @Override
    public void onInterrupt() { }

    @Override
    public boolean onUnbind(Intent intent) {
        instance = null;
        return super.onUnbind(intent);
    }

    public static boolean isReady() { return instance != null; }

    public static void back()          { if (instance != null) instance.performGlobalAction(GLOBAL_ACTION_BACK); }
    public static void home()          { if (instance != null) instance.performGlobalAction(GLOBAL_ACTION_HOME); }
    public static void recents()       { if (instance != null) instance.performGlobalAction(GLOBAL_ACTION_RECENTS); }
    public static void notifications() { if (instance != null) instance.performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS); }

    /** Lanza una app por paquete (el contexto de accesibilidad puede en 2o plano). */
    public static void launch(String pkg) {
        if (instance == null) return;
        try {
            Intent i = instance.getPackageManager().getLaunchIntentForPackage(pkg);
            if (i != null) {
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                instance.startActivity(i);
            }
        } catch (Exception ignored) {}
    }
}
