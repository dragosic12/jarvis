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

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;
import java.util.Locale;

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
    private static volatile long armShutterUntil = 0; // ventana para auto-disparo de foto
    private static volatile long armShutterAt = 0;

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

        // Auto-disparo de foto: si esta armado y hay una camara delante, pulsa el obturador
        if (armShutterUntil > SystemClock.uptimeMillis() && isCameraPkg(curPkg)) {
            if (tryClickShutter()) armShutterUntil = 0;
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

    /** Arma el auto-disparo: durante ~6s, al ver una camara delante, pulsa el obturador. */
    public static void armShutter() {
        armShutterUntil = SystemClock.uptimeMillis() + 6000;
        armShutterAt = SystemClock.uptimeMillis();
    }

    private static boolean isCameraPkg(String pkg) {
        if (pkg == null) return false;
        String p = pkg.toLowerCase(Locale.ROOT);
        return p.contains("camera") || p.contains("camara") || p.contains("gcam");
    }

    /** Pulsa el obturador: por descripcion, y si no, toca donde suele estar (abajo-centro). */
    private boolean tryClickShutter() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root != null) {
            try {
                AccessibilityNodeInfo d = findByDesc(root, new String[]{
                        "obturador", "hacer foto", "tomar foto", "capturar", "disparar",
                        "hacer una foto", "sacar foto", "boton del obturador",
                        "shutter", "take photo", "take picture", "capture"});
                if (clickNode(d)) return true;
            } catch (Exception ignored) {}
        }
        // Fallback por coordenada, tras dar ~1,2s a que cargue la camara
        if (SystemClock.uptimeMillis() - armShutterAt < 1200) return false;
        try {
            DisplayMetrics dm = getResources().getDisplayMetrics();
            float x = dm.widthPixels / 2f;
            float y = dm.heightPixels * 0.88f;
            Path path = new Path();
            path.moveTo(x, y);
            GestureDescription gd = new GestureDescription.Builder()
                    .addStroke(new GestureDescription.StrokeDescription(path, 0, 60))
                    .build();
            dispatchGesture(gd, null, null);
            return true;
        } catch (Exception e) { return false; }
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

    // ==================== FASE 3: reproducir rutinas por voz ====================

    private static final int MAX_PLAY_STEPS = 200;        // tope de pasos por reproduccion
    private static final long MAX_PLAY_MS = 5 * 60_000L;  // tope duro de duracion (5 min)
    private static volatile boolean playing = false;

    public static boolean isPlaying() { return playing; }

    /** Reproduce una rutina guardada (por su slug) reejecutando sus pasos:
     *  cambios de app -> launch(pkg); clicks/scrolls -> localizar el nodo y
     *  performAction(), con fallback a un tap por coordenada grabada. Corre
     *  en un hilo aparte para no bloquear el pipeline de voz; el resultado
     *  (empieza/termina/error/no encontrada) se anuncia por voz a traves de
     *  ListeningService.routineAnnounce() -- mismo patron que el modo coche. */
    public static void playRoutine(String rawSlug) {
        String slug = rawSlug == null ? "" : rawSlug.trim();
        String spoken = slug.replace('_', ' ').trim();
        if (instance == null) {
            ListeningService.routineAnnounce("Necesito el servicio de accesibilidad Jarvis Gestos activado para reproducir rutinas.");
            return;
        }
        if (playing) {
            ListeningService.routineAnnounce("Ya estoy con una rutina, espera a que termine.");
            return;
        }
        JSONObject data = RoutineRecorder.loadRoutine(instance, slug);
        if (data == null) {
            ListeningService.routineAnnounce("No encuentro ninguna rutina llamada "
                    + (spoken.isEmpty() ? "esa" : spoken) + ".");
            return;
        }
        final JarvisA11yService svc = instance;
        playing = true;
        ListeningService.routineAnnounce("Ejecutando la rutina " + spoken + ".");
        new Thread(() -> {
            boolean ok;
            try {
                svc.runRoutineSteps(data);
                ok = true;
            } catch (Exception e) {
                ok = false;
            } finally {
                playing = false;
            }
            ListeningService.routineAnnounce(ok ? "Rutina " + spoken + " terminada."
                    : "La rutina " + spoken + " se ha parado por un error.");
        }, "JarvisRoutinePlay").start();
    }

    /** Reproduce, en orden, los pasos guardados de una rutina. Un paso que
     *  falla no aborta el resto (se salta); si el servicio de accesibilidad
     *  se desactiva a media reproduccion o se supera el tope de tiempo, se
     *  corta limpiamente. */
    private void runRoutineSteps(JSONObject data) {
        JSONArray evs = data.optJSONArray("events");
        if (evs == null) return;
        int n = Math.min(evs.length(), MAX_PLAY_STEPS);
        long deadline = SystemClock.elapsedRealtime() + MAX_PLAY_MS;
        String curAppPkg = null;

        for (int i = 0; i < n; i++) {
            if (instance == null) break;                          // servicio desactivado a media reproduccion
            if (SystemClock.elapsedRealtime() > deadline) break;   // tope de tiempo de seguridad
            JSONObject ev = evs.optJSONObject(i);
            if (ev == null) continue;
            String type = ev.optString("type", "");
            try {
                if ("app_change".equals(type)) {
                    String pkg = ev.optString("pkg", "");
                    if (!pkg.isEmpty() && !pkg.equals(curAppPkg)) {
                        launch(pkg);
                        curAppPkg = pkg;
                        waitForPackage(pkg, 3000);
                    }
                } else if ("click".equals(type) || "long_click".equals(type)) {
                    performRecordedTap(ev, "long_click".equals(type));
                    sleepQuiet(900);
                } else if ("scroll".equals(type)) {
                    dispatchSwipe(ev.optString("dir", "down"));
                    sleepQuiet(900);
                }
            } catch (Exception stepErr) {
                // un paso suelto que falla no debe tirar abajo toda la rutina
            }
        }
    }

    /** Espera activa (con tope) a que la app en primer plano sea pkg, para dar
     *  tiempo a que cargue tras lanzarla antes de tocar nada. */
    private void waitForPackage(String pkg, long maxMs) {
        long start = SystemClock.elapsedRealtime();
        while (SystemClock.elapsedRealtime() - start < maxMs) {
            if (pkg.equals(curPkg)) return;
            sleepQuiet(120);
        }
    }

    private void sleepQuiet(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
        }
    }

    /** Reproduce un click/long-click grabado: intenta localizar el nodo por
     *  viewId, luego por content-description, y hace performAction() sobre el
     *  o su primer ancestro clickable/long-clickable. Si no aparece (la UI
     *  cambio desde que se grabo), cae a un tap/long-tap por la coordenada
     *  (x,y) grabada como respaldo. */
    private void performRecordedTap(JSONObject ev, boolean longClick) {
        String viewId = ev.optString("viewId", "");
        String desc = ev.optString("desc", "");
        int x = ev.optInt("x", -1), y = ev.optInt("y", -1);

        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root != null) {
            try {
                AccessibilityNodeInfo target = null;
                if (!viewId.isEmpty()) {
                    List<AccessibilityNodeInfo> byId = root.findAccessibilityNodeInfosByViewId(viewId);
                    if (byId != null && !byId.isEmpty()) target = byId.get(0);
                }
                if (target == null && !desc.isEmpty()) {
                    target = findByDesc(root, new String[]{desc.toLowerCase(Locale.ROOT)});
                }
                if (target != null) {
                    int action = longClick ? AccessibilityNodeInfo.ACTION_LONG_CLICK : AccessibilityNodeInfo.ACTION_CLICK;
                    if (performActionOnNode(target, action)) return;
                }
            } catch (Exception ignored) { }
        }
        // Fallback: tap/long-tap por coordenada grabada
        if (x >= 0 && y >= 0) dispatchTap(x, y, longClick);
    }

    /** Como clickNode() pero para una accion generica (click o long-click),
     *  usada solo en reproduccion de rutinas; no toca clickNode() (WhatsApp). */
    private boolean performActionOnNode(AccessibilityNodeInfo n, int action) {
        if (n == null) return false;
        boolean wantLong = action == AccessibilityNodeInfo.ACTION_LONG_CLICK;
        AccessibilityNodeInfo c = n;
        for (int i = 0; i < 6 && c != null; i++) {
            boolean ok = wantLong ? c.isLongClickable() : c.isClickable();
            if (ok) break;
            c = c.getParent();
        }
        try {
            if (c != null) return c.performAction(action);
            return n.performAction(action);
        } catch (Exception e) {
            return false;
        }
    }

    /** Tap (o long-tap) por coordenada absoluta, respaldo cuando no se
     *  encuentra el nodo grabado. */
    private void dispatchTap(int x, int y, boolean longClick) {
        try {
            Path path = new Path();
            path.moveTo(x, y);
            long duration = longClick ? 600 : 80;
            GestureDescription gd = new GestureDescription.Builder()
                    .addStroke(new GestureDescription.StrokeDescription(path, 0, duration))
                    .build();
            dispatchGesture(gd, null, null);
        } catch (Exception ignored) { }
    }

    /** Reproduce un scroll grabado en la direccion aproximada guardada.
     *  Vertical reutiliza swipe(); horizontal usa un gesto propio (no habia
     *  helper existente para eso). */
    private void dispatchSwipe(String dir) {
        if ("down".equals(dir)) { swipe(true); return; }
        if ("up".equals(dir)) { swipe(false); return; }
        if (!"left".equals(dir) && !"right".equals(dir)) return; // "unknown": no sabemos que gesto hacer
        try {
            DisplayMetrics dm = getResources().getDisplayMetrics();
            float y = dm.heightPixels / 2f;
            float x1 = "left".equals(dir) ? dm.widthPixels * 0.80f : dm.widthPixels * 0.20f;
            float x2 = "left".equals(dir) ? dm.widthPixels * 0.20f : dm.widthPixels * 0.80f;
            Path path = new Path();
            path.moveTo(x1, y);
            path.lineTo(x2, y);
            GestureDescription gd = new GestureDescription.Builder()
                    .addStroke(new GestureDescription.StrokeDescription(path, 0, 200))
                    .build();
            dispatchGesture(gd, null, null);
        } catch (Exception ignored) { }
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
