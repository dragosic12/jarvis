package com.drale.jarvis;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Build;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.util.List;

/**
 * Servicio de Accesibilidad: la UNICA via para ejecutar acciones del sistema
 * (atras, inicio, recientes, notificaciones) desde una app. Lo dispara
 * FaceGestureService cuando detecta un gesto. El usuario lo activa una vez en
 * Ajustes -> Accesibilidad -> Jarvis Gestos.
 */
public class JarvisA11yService extends AccessibilityService {

    private static JarvisA11yService instance;
    private static volatile String curPkg = "";
    private static volatile long armSendUntil = 0;   // ventana para auto-enviar WhatsApp

    @Override
    protected void onServiceConnected() {
        instance = this;
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) return;
        int type = event.getEventType();

        // Rastrea la app en primer plano (para gestos que cambian segun la app)
        if (type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            CharSequence p = event.getPackageName();
            if (p != null) {
                String s = p.toString();
                if (!s.contains("systemui") && !s.contains("inputmethod") && !s.equals("android")) {
                    if (RoutineRecorder.isRecording() && !s.equals(curPkg)) {
                        RoutineRecorder.logAppChange(s);
                    }
                    curPkg = s;
                }
            }
        }

        // Auto-enviar WhatsApp: si esta armado y WhatsApp esta delante, pulsa "Enviar".
        // Se reintenta en cada evento (la UI tarda en cargar el texto tras abrir el chat).
        if (armSendUntil > SystemClock.uptimeMillis() && "com.whatsapp".equals(curPkg)) {
            if (tryClickSend()) armSendUntil = 0;
        }

        // --- FASE 1: grabador de rutinas ------------------------------------
        // typeViewClicked/typeViewLongClicked/typeViewScrolled llegan aqui para
        // TODAS las apps del sistema (asi lo exige a11y_config.xml para poder
        // capturarlos cuando SI se este grabando), asi que el filtro por
        // "isRecording()" tiene que ser lo PRIMERO y lo mas barato posible para
        // no afectar al rendimiento cuando no se esta grabando (caso normal).
        if (RoutineRecorder.isRecording()
                && (type == AccessibilityEvent.TYPE_VIEW_CLICKED
                    || type == AccessibilityEvent.TYPE_VIEW_LONG_CLICKED
                    || type == AccessibilityEvent.TYPE_VIEW_SCROLLED)) {
            try {
                recordRoutineEvent(event, type);
            } catch (Exception ignored) { }
        }
    }

    /** Registra un click/long-click/scroll en la rutina que se esta grabando.
     *  Nunca graba texto tecleado (no escuchamos typeViewTextChanged) ni campos
     *  de contrasena (isPassword()), y se salta apps sensibles (banca, gestores
     *  de contrasenas) por completo. */
    private void recordRoutineEvent(AccessibilityEvent event, int type) {
        if (RoutineRecorder.isSensitiveApp(curPkg)) return;

        AccessibilityNodeInfo src = event.getSource();
        if (src == null) return;
        try {
            if (src.isPassword()) return; // nunca campos de contrasena

            Rect bounds = new Rect();
            src.getBoundsInScreen(bounds);
            int cx = bounds.centerX(), cy = bounds.centerY();
            String viewId = src.getViewIdResourceName();
            CharSequence descCs = src.getContentDescription();
            String desc = descCs != null ? descCs.toString() : null;

            if (type == AccessibilityEvent.TYPE_VIEW_CLICKED) {
                RoutineRecorder.logEvent("click", curPkg, viewId, desc, cx, cy, null);
            } else if (type == AccessibilityEvent.TYPE_VIEW_LONG_CLICKED) {
                RoutineRecorder.logEvent("long_click", curPkg, viewId, desc, cx, cy, null);
            } else if (type == AccessibilityEvent.TYPE_VIEW_SCROLLED) {
                RoutineRecorder.logEvent("scroll", curPkg, viewId, desc, cx, cy, scrollDirection(event));
            }
        } finally {
            try { src.recycle(); } catch (Exception ignored) { }
        }
    }

    /** Direccion aproximada del scroll ('up'/'down'/'left'/'right'/'unknown'). */
    private String scrollDirection(AccessibilityEvent event) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                int dx = event.getScrollDeltaX();
                int dy = event.getScrollDeltaY();
                if (dx == 0 && dy == 0) return "unknown";
                return Math.abs(dy) >= Math.abs(dx) ? (dy > 0 ? "down" : "up") : (dx > 0 ? "right" : "left");
            }
        } catch (Exception ignored) { }
        return "unknown";
    }

    public static String currentPackage() { return curPkg; }

    /** Arma el auto-envio: durante los proximos 9s, al ver WhatsApp delante, pulsa enviar. */
    public static void armSend() {
        armSendUntil = SystemClock.uptimeMillis() + 9000;
    }

    /** Busca el boton de enviar de WhatsApp y lo pulsa. Devuelve true si lo consiguio. */
    private boolean tryClickSend() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return false;
        try {
            // 1) por id del boton de enviar (lo mas fiable entre versiones)
            List<AccessibilityNodeInfo> byId = root.findAccessibilityNodeInfosByViewId("com.whatsapp:id/send");
            if (byId != null) {
                for (AccessibilityNodeInfo n : byId) {
                    if (clickNode(n)) return true;
                }
            }
            // 2) fallback: por descripcion "Enviar"/"Send" recorriendo el arbol
            AccessibilityNodeInfo bydesc = findByDesc(root, new String[]{"enviar", "send"});
            if (clickNode(bydesc)) return true;
        } catch (Exception ignored) {}
        return false;
    }

    /** Pulsa el nodo (o su primer ancestro clickable). */
    private boolean clickNode(AccessibilityNodeInfo n) {
        if (n == null) return false;
        AccessibilityNodeInfo c = n;
        for (int i = 0; i < 4 && c != null && !c.isClickable(); i++) c = c.getParent();
        try {
            if (c != null && c.isClickable()) return c.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            return n.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        } catch (Exception e) { return false; }
    }

    /** DFS: primer nodo cuya content-description coincida exactamente con alguna de descs. */
    private AccessibilityNodeInfo findByDesc(AccessibilityNodeInfo node, String[] descs) {
        if (node == null) return null;
        CharSequence cd = node.getContentDescription();
        if (cd != null) {
            String s = cd.toString().toLowerCase().trim();
            for (String d : descs) if (s.equals(d) || s.startsWith(d + " ")) return node;
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo r = findByDesc(node.getChild(i), descs);
            if (r != null) return r;
        }
        return null;
    }

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
