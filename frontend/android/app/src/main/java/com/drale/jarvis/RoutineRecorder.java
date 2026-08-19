package com.drale.jarvis;

import android.content.Context;
import android.os.SystemClock;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Grabador de rutinas.
 *
 * FASE 1: captura la secuencia de acciones del usuario (toques, toques
 * largos, scrolls, cambios de app) mientras el modo grabacion esta activo.
 * FASE 2: analiza lo grabado (apps mas usadas, secuencias de 2 pasos que mas
 * se repiten). FASE 3: guarda las rutinas con NOMBRE y las reproduce por voz.
 *
 * Lo alimenta JarvisA11yService (recibe los eventos de accesibilidad y
 * reproduce los pasos) y lo controla por voz ListeningService
 * (jarvis-routine://record-start|record-stop[:nombre]|list|analyze|play:nombre).
 *
 * PRIVACIDAD: no se graba texto tecleado (no escuchamos typeViewTextChanged),
 * ni nodos marcados como campo de contrasena (isPassword()), ni nada mientras
 * una app sensible (banca, gestor de contrasenas) esta en primer plano. Todo
 * se queda en el propio movil (filesDir/routines/) y el analisis (FASE 2)
 * tambien se hace enteramente ahi; no se sube nada a ningun sitio.
 */
public class RoutineRecorder {

    private static final String TAG = "JarvisRoutine";
    private static final int MAX_EVENTS = 400;                 // limite de seguridad por rutina
    private static final long MAX_RECORDING_MS = 10 * 60_000L; // auto-stop de seguridad a los 10 min
    private static final int MAX_NAME_LEN = 40;

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

    /** Para la grabacion y guarda lo capturado SIN nombre (fecha automatica). */
    public static synchronized int stopRecording(Context ctx) {
        return stopRecording(ctx, null);
    }

    /** Para la grabacion y guarda lo capturado en filesDir/routines/, con
     *  nombre opcional (FASE 3: para poder reproducirla luego por voz).
     *  Si se repite un nombre ya usado, sobreescribe esa rutina.
     *  Devuelve el numero de pasos guardados (0 si no habia nada que guardar). */
    public static synchronized int stopRecording(Context ctx, String rawName) {
        recording = false;
        int n = events.size();
        if (n == 0) {
            events.clear();
            Log.i(TAG, "Grabacion parada sin eventos: no se guarda nada");
            return 0;
        }
        try {
            File dir = routinesDir(ctx);
            if (!dir.exists()) dir.mkdirs();
            String slug = safeSlug(rawName);
            JSONObject root = new JSONObject();
            root.put("saved_at", System.currentTimeMillis());
            root.put("event_count", n);
            root.put("name", slug != null ? slug : "");
            root.put("events", new JSONArray(events));
            String filename = slug != null ? ("routine_" + slug + ".json")
                                            : ("routine_" + System.currentTimeMillis() + ".json");
            File f = new File(dir, filename);
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
            File dir = routinesDir(ctx);
            String[] files = dir.list((d, name) -> name.startsWith("routine_") && name.endsWith(".json"));
            return files == null ? 0 : files.length;
        } catch (Exception e) {
            return 0;
        }
    }

    /** Carga una rutina guardada por su slug (FASE 3, para reproducirla).
     *  Primero prueba el fichero exacto routine_&lt;slug&gt;.json; si no
     *  existe, busca por coincidencia parcial del nombre (tolera pequenas
     *  diferencias entre como se dijo al grabar y al reproducir). Devuelve
     *  null si no hay ninguna rutina que case. */
    public static JSONObject loadRoutine(Context ctx, String rawSlug) {
        String slug = safeSlug(rawSlug);
        if (slug == null) return null;
        File dir = routinesDir(ctx);
        File exact = new File(dir, "routine_" + slug + ".json");
        File f = exact.exists() ? exact : findByFuzzyName(dir, slug);
        if (f == null) return null;
        try {
            return new JSONObject(readFile(f));
        } catch (Exception e) {
            Log.w(TAG, "No se pudo leer la rutina " + f.getName() + ": " + e);
            return null;
        }
    }

    private static File findByFuzzyName(File dir, String slug) {
        File[] files = dir.listFiles((d, name) -> name.startsWith("routine_") && name.endsWith(".json"));
        if (files == null) return null;
        for (File f : files) {
            String base = baseName(f);
            if (slug.equals(base)) return f;
        }
        for (File f : files) {
            String base = baseName(f);
            if (!base.isEmpty() && (base.contains(slug) || slug.contains(base))) return f;
        }
        return null;
    }

    private static String baseName(File f) {
        String n = f.getName();
        if (n.startsWith("routine_") && n.endsWith(".json")) {
            return n.substring("routine_".length(), n.length() - ".json".length());
        }
        return "";
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

    // ---- FASE 2: analizar lo mas repetido ---------------------------------

    /** Resumen hablable de lo mas repetido en todas las rutinas guardadas:
     *  la app que mas aparece y la secuencia de 2 pasos (mismo pkg+viewId
     *  seguidos) que mas se repite entre rutinas. Todo el analisis se hace
     *  leyendo unicamente routine_*.json de filesDir; nada sale del movil. */
    public static String analyzeSpoken(Context ctx) {
        File dir = routinesDir(ctx);
        File[] files = dir.listFiles((d, name) -> name.startsWith("routine_") && name.endsWith(".json"));
        if (files == null || files.length == 0) {
            return "Todavia no tengo rutinas grabadas para analizar.";
        }

        Map<String, Integer> appCount = new HashMap<>();
        Map<String, Integer> bigramCount = new HashMap<>();
        Map<String, String> bigramLabel = new HashMap<>();

        for (File f : files) {
            JSONObject root;
            try {
                root = new JSONObject(readFile(f));
            } catch (Exception e) {
                continue;
            }
            JSONArray evs = root.optJSONArray("events");
            if (evs == null) continue;
            String prevKey = null, prevLabel = null;
            for (int i = 0; i < evs.length(); i++) {
                JSONObject ev = evs.optJSONObject(i);
                if (ev == null) continue;
                String pkg = ev.optString("pkg", "");
                String type = ev.optString("type", "");
                if (!pkg.isEmpty() && ("click".equals(type) || "long_click".equals(type) || "app_change".equals(type))) {
                    appCount.merge(pkg, 1, Integer::sum);
                }
                if ("click".equals(type) || "long_click".equals(type)) {
                    String id = ev.optString("viewId", "");
                    String key = pkg + "|" + id;
                    String label = appLabel(pkg) + (ev.has("desc") && !ev.optString("desc").isEmpty()
                            ? (": " + ev.optString("desc")) : "");
                    if (prevKey != null && !prevKey.equals(key)) {
                        String bk = prevKey + ">" + key;
                        bigramCount.merge(bk, 1, Integer::sum);
                        bigramLabel.putIfAbsent(bk, prevLabel + " y luego " + label);
                    }
                    prevKey = key;
                    prevLabel = label;
                }
            }
        }

        String topApp = null;
        int topAppN = 0;
        for (Map.Entry<String, Integer> e : appCount.entrySet()) {
            if (e.getValue() > topAppN) {
                topAppN = e.getValue();
                topApp = e.getKey();
            }
        }
        String topBigram = null;
        int topBigramN = 0;
        for (Map.Entry<String, Integer> e : bigramCount.entrySet()) {
            if (e.getValue() > topBigramN) {
                topBigramN = e.getValue();
                topBigram = e.getKey();
            }
        }

        StringBuilder sb = new StringBuilder();
        sb.append("He mirado ").append(files.length).append(files.length == 1 ? " rutina. " : " rutinas. ");
        if (topApp != null) {
            sb.append("La app que mas usas es ").append(appLabel(topApp)).append(". ");
        }
        if (topBigram != null && topBigramN >= 2) {
            sb.append("Lo que mas repites es: ").append(bigramLabel.get(topBigram)).append(".");
        } else {
            sb.append("Todavia no veo una secuencia que se repita claramente entre rutinas.");
        }
        return sb.toString();
    }

    private static String appLabel(String pkg) {
        if (pkg == null || pkg.isEmpty()) return "una app";
        int dot = pkg.lastIndexOf('.');
        return dot >= 0 ? pkg.substring(dot + 1) : pkg;
    }

    // ---- utilidades ---------------------------------------------------

    private static File routinesDir(Context ctx) {
        return new File(ctx.getFilesDir(), "routines");
    }

    /** Nombre de rutina -> slug seguro (solo [a-z0-9_], max 40). Se aplica
     *  tanto al guardar como al buscar, asi que grabar y reproducir con la
     *  misma frase casa exactamente. Tambien evita cualquier caracter raro
     *  en el nombre de fichero (el nombre viene del backend ya limpio, pero
     *  se vuelve a sanear aqui por seguridad). */
    private static String safeSlug(String s) {
        if (s == null) return null;
        String x = s.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9_]", "");
        if (x.length() > MAX_NAME_LEN) x = x.substring(0, MAX_NAME_LEN);
        x = x.replaceAll("^_+|_+$", "");
        return x.isEmpty() ? null : x;
    }

    private static String readFile(File f) throws Exception {
        FileInputStream fis = new FileInputStream(f);
        try {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int r;
            while ((r = fis.read(buf)) != -1) bos.write(buf, 0, r);
            return bos.toString("UTF-8");
        } finally {
            fis.close();
        }
    }
}
