package com.drale.jarvis;

import android.content.Context;
import android.os.SystemClock;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * FASE 1 del grabador de rutinas: captura la secuencia de acciones del usuario
 * (toques, toques largos, scrolls, cambios de app) mientras el modo grabacion
 * esta activo, para mas adelante (fase 2-3) poder detectar secuencias repetidas
 * y reproducirlas por voz con dispatchGesture()/performAction().
 *
 * Lo alimenta JarvisA11yService (recibe los eventos de accesibilidad) y lo
 * controla por voz ListeningService (jarvis-routine://record-start|record-stop|list).
 *
 * PRIVACIDAD: no se graba texto tecleado (no escuchamos typeViewTextChanged),
 * ni nodos marcados como campo de contrasena (isPassword()), ni nada mientras
 * una app sensible (banca, gestor de contrasenas) esta en primer plano. Todo
 * se queda en el propio movil (filesDir/routines/); no se sube a ningun sitio.
 */
public class RoutineRecorder {

    private static final String TAG = "JarvisRoutine";
    private static final int MAX_EVENTS = 400;                 // limite de seguridad por rutina
    private static final long MAX_RECORDING_MS = 10 * 60_000L; // auto-stop de seguridad a los 10 min

    // Apps sensibles: mientras alguna de estas este en primer plano no se graba
    // ningun evento (coincide por subcadena en el nombre de paquete, en minusculas).
    private static final Set<String> SENSITIVE_PKG_KEYWORDS = new HashSet<>(Arrays.asList(
            "bbva", "santander", "caixabank", "lacaixa", "bankinter", "sabadell",
            "openbank", "evobanco", "unicaja", "ingdirect", "revolut", "n26",
            "wise.com", "transferwise", "paypal", "bizum", "wallet",
            "password", "keepass", "bitwarden", "lastpass", "1password", "dashlane",
            "authenticator", "authy", "protonpass"
    ));

    private static volatile boolean recording = false;
    private static volatile long startedAtElapsed = 0;
    private static volatile String lastLoggedPkg = "";
    private static final List<JSONObject> events = new ArrayList<>();

    private RoutineRecorder() { }

    public static boolean isRecording() {
        return recording;
    }

    /** ¿Hay que pausar la captura porque esta app es sensible (banca, contrasenas)? */
    public static boolean isSensitiveApp(String pkg) {
        if (pkg == null) return false;
        String p = pkg.toLowerCase(Locale.ROOT);
        for (String k : SENSITIVE_PKG_KEYWORDS) {
            if (p.contains(k)) return true;
        }
        return false;
    }

    /** Empieza una grabacion nueva (descarta cualquier evento previo sin guardar). */
    public static synchronized void startRecording() {
        events.clear();
        lastLoggedPkg = "";
        startedAtElapsed = SystemClock.elapsedRealtime();
        recording = true;
        Log.i(TAG, "Grabacion de rutina iniciada");
    }

    /** Para la grabacion y guarda lo capturado en filesDir/routines/. Devuelve el
     *  numero de pasos guardados (0 si no habia nada que guardar). */
    public static synchronized int stopRecording(Context ctx) {
        recording = false;
        int n = events.size();
        if (n == 0) {
            Log.i(TAG, "Grabacion parada sin eventos: no se guarda nada");
            return 0;
        }
        try {
            File dir = new File(ctx.getFilesDir(), "routines");
            if (!dir.exists()) dir.mkdirs();
            JSONObject root = new JSONObject();
            root.put("saved_at", System.currentTimeMillis());
            root.put("event_count", n);
            root.put("events", new JSONArray(events));
            File f = new File(dir, "routine_" + System.currentTimeMillis() + ".json");
            try (FileOutputStream fos = new FileOutputStream(f)) {
                fos.write(root.toString().getBytes("UTF-8"));
            }
            Log.i(TAG, "Rutina guardada: " + f.getName() + " (" + n + " pasos)");
        } catch (Exception e) {
            Log.w(TAG, "No se pudo guardar la rutina: " + e);
        } finally {
            events.clear();
        }
        return n;
    }

    /** Numero de rutinas guardadas en el dispositivo (para "lista mis rutinas"). */
    public static int countRoutines(Context ctx) {
        try {
            File dir = new File(ctx.getFilesDir(), "routines");
            String[] files = dir.list((d, name) -> name.startsWith("routine_") && name.endsWith(".json"));
            return files == null ? 0 : files.length;
        } catch (Exception e) {
            return 0;
        }
    }

    /** Click/long-click/scroll sobre un elemento. No hace nada si no se esta
     *  grabando o si la app en primer plano es sensible. */
    public static synchronized void logEvent(String type, String pkg, String viewId, String desc,
                                              int x, int y, String extra) {
        if (!recording) return;
        if (isSensitiveApp(pkg)) return; // pausa silenciosa en apps sensibles
        if (events.size() >= MAX_EVENTS || overTimeLimit()) {
            autoStopSafety();
            return;
        }
        try {
            JSONObject o = new JSONObject();
            o.put("t", SystemClock.elapsedRealtime() - startedAtElapsed);
            o.put("type", type);
            o.put("pkg", pkg == null ? "" : pkg);
            if (viewId != null) o.put("viewId", viewId);
            if (desc != null && !desc.isEmpty()) o.put("desc", desc);
            o.put("x", x);
            o.put("y", y);
            if (extra != null) o.put("dir", extra);
            events.add(o);
            lastLoggedPkg = pkg;
            Log.d(TAG, "evt " + type + " pkg=" + pkg + " id=" + viewId + " desc=" + desc
                    + " (" + x + "," + y + ")" + (extra == null ? "" : " dir=" + extra));
        } catch (Exception ignored) { }
    }

    /** Cambio de app en primer plano durante la grabacion. */
    public static synchronized void logAppChange(String pkg) {
        if (!recording) return;
        if (pkg == null || pkg.equals(lastLoggedPkg)) return;
        if (events.size() >= MAX_EVENTS || overTimeLimit()) {
            autoStopSafety();
            return;
        }
        try {
            JSONObject o = new JSONObject();
            o.put("t", SystemClock.elapsedRealtime() - startedAtElapsed);
            o.put("type", "app_change");
            o.put("pkg", pkg);
            events.add(o);
            lastLoggedPkg = pkg;
            Log.d(TAG, "evt app_change pkg=" + pkg);
        } catch (Exception ignored) { }
    }

    private static boolean overTimeLimit() {
        return SystemClock.elapsedRealtime() - startedAtElapsed > MAX_RECORDING_MS;
    }

    /** Corta la grabacion por seguridad (limite de eventos o de tiempo). Lo ya
     *  capturado NO se pierde ni se descarta: sigue en memoria hasta que el
     *  usuario diga "termina la rutina", que lo guardara con lo que haya. */
    private static void autoStopSafety() {
        if (!recording) return;
        recording = false;
        Log.w(TAG, "Grabacion parada automaticamente (limite de eventos o de tiempo alcanzado)");
    }

    // ---- FASE 2-3 (andamiaje, sin implementar todavia) -------------------
    // TODO: minar routine_*.json en busca de secuencias de pasos que se
    //       repiten (mismo pkg+viewId en el mismo orden) para sugerir rutinas.
    // TODO: reproducir una rutina guardada por voz ("haz la rutina X"):
    //       leer el JSON y para cada evento, si hay viewId/desc intentar
    //       localizar el nodo con findAccessibilityNodeInfosByViewId()/
    //       recorrido por content-description (como tryClickSend() en
    //       JarvisA11yService) y si no se encuentra, hacer dispatchGesture()
    //       con un tap en (x,y) como respaldo. Cuidado: la UI puede haber
    //       cambiado de sitio entre grabacion y reproduccion.
}
