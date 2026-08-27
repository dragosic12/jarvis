package com.drale.jarvis;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.bluetooth.BluetoothDevice;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.media.MediaPlayer;
import android.media.ToneGenerator;
import android.media.AudioManager;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.BatteryManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.os.Vibrator;
import android.os.VibrationEffect;
import android.speech.tts.TextToSpeech;

import androidx.core.app.NotificationCompat;
import androidx.core.content.FileProvider;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.text.Normalizer;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Escucha continua NATIVA: graba con AudioRecord, detecta voz por energia,
 * envia el audio al backend, reconoce la wake word "Jarvis" y ejecuta el
 * comando (abrir apps, TTS de respuestas). Corre en el servicio en primer
 * plano, asi que sigue funcionando con la app cerrada o la pantalla apagada
 * -- a diferencia del WebView, que Android congela en segundo plano.
 */
public class ListeningService extends Service {

    private static final String CHANNEL_ID = "jarvis_listening";
    private static final int NOTIF_ID = 1001;

    // Parametros de VAD (equivalentes a la version JS)
    private static final int SAMPLE_RATE = 16000;
    // Ajustables en caliente desde el panel (GET /api/settings); estos son los defaults.
    private static volatile double SILENCE_RMS = 0.0020;  // mas bajo = mas sensible (voz lejana/floja)
    private static final int NORM_TARGET = 29000;      // pico objetivo tras normalizar (~0.9)
    private static volatile float NORM_MAX_GAIN = 18.0f;  // tope de amplificacion adaptativa (voz muy floja)
    private static volatile long SILENCE_MS = 700;        // silencio tras voz -> cortar (mas agil)
    private static volatile long MIN_SPEECH_MS = 300;
    private static volatile double SPEECH_MULT = 2.0;  // voz = suelo de ruido * esto (mas bajo = mas sensible)
    private static final double NOISE_CAP = 0.03;      // tope del suelo de ruido estimado
    private static final long MAX_SEG_MS = 15000;
    private static final long NO_SPEECH_WAKE_MS = 8000;
    private static final long NO_SPEECH_ARMED_MS = 6000;
    private static final long NO_SPEECH_CONV_MS = 12000;   // modo conversacion: mas margen
    private static final int MIN_PCM_BYTES = 6000;      // ~0.19s: descartar clics (mas permisivo)

    // Cualquier palabra que suene a "Jarvis": j/y/g/h + vocal + r opcional (Whisper
    // se la come: "ya vais") + d/t opcional ("yardvis") + v/b + vocal opcional
    // ("vais") + i + s. Pilla jarvis, yarvis, gervis, jarbis, yardvis, ya vais...
    private static final Pattern WAKE_RE =
            Pattern.compile("^(?:ch|[jyghx])[ae]+r*[dt]?[bvw]+[ae]*i+[sz]*$");

    private PowerManager.WakeLock wakeLock;
    private volatile boolean running = false;
    private Thread audioThread;
    private String apiBase = "";
    private String token = "";
    private TextToSpeech tts;
    private volatile MediaPlayer ttsPlayer;   // voz del servidor (voz masculina Alvaro)
    private volatile boolean convMode = false;   // modo conversacion (Iron Man)
    private ToneGenerator tone;

    private static ListeningService self;         // para que el NotifListener hable
    private volatile boolean carMode = false;     // modo coche (lee mensajes en alto)
    private int carOldMusicVol = -1;              // volumen de musica antes del modo coche
    private volatile String pendingAudioJid = ""; // WhatsApp: grabar el proximo audio para este numero
    private BroadcastReceiver btReceiver;         // auto-modo-coche por Bluetooth
    private volatile String lastBtAddr = "";      // ultimo bluetooth conectado

    // Frases para salir del modo conversacion (sin ir al servidor)
    private static final Pattern EXIT_RE = Pattern.compile(
            "\\b(gracias|adios|adios jarvis|hasta luego|hasta ahora|modo normal|ya esta|"
            + "nada mas|sal del modo|dejalo ya|se acabo|eso es todo|corta ya|ya vale|"
            + "para|para ya|parate|basta|ya basta|sal|salir|callate|calla|silencio|"
            + "deja de escuchar|para de escuchar|dejalo|termina)\\b");

    private boolean isExitPhrase(String text) {
        String n = Normalizer.normalize(text.toLowerCase(Locale.ROOT), Normalizer.Form.NFD)
                .replaceAll("\\p{Mn}", "").trim();
        int words = n.isEmpty() ? 0 : n.split("\\s+").length;
        return words > 0 && words <= 4 && EXIT_RE.matcher(n).find();
    }

    @Override
    public void onCreate() {
        super.onCreate();
        self = this;
        registerBtReceiver();
        try { tone = new ToneGenerator(AudioManager.STREAM_MUSIC, 70); } catch (Exception ignored) {}

        // Muchos moviles (Oppo/Realme) no traen motor de voz por defecto en
        // espanol. Si Google TTS esta instalado, usarlo explicitamente en vez
        // del motor del sistema (que aqui es null/chino y no habla).
        String engine = null;
        try {
            getPackageManager().getPackageInfo("com.google.android.tts", 0);
            engine = "com.google.android.tts";
        } catch (Exception ignored) {}

        TextToSpeech.OnInitListener init = status -> {
            if (status == TextToSpeech.SUCCESS && tts != null) {
                int r = tts.setLanguage(new Locale("es", "ES"));
                if (r == TextToSpeech.LANG_MISSING_DATA || r == TextToSpeech.LANG_NOT_SUPPORTED) {
                    tts.setLanguage(new Locale("es"));
                }
            }
        };
        tts = (engine != null) ? new TextToSpeech(this, init, engine)
                               : new TextToSpeech(this, init);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            if (intent.getStringExtra("apiBase") != null) apiBase = intent.getStringExtra("apiBase");
            if (intent.getStringExtra("token") != null) token = intent.getStringExtra("token");
        }

        startForegroundNotification();

        if (wakeLock == null) {
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:listening");
            wakeLock.acquire();
        }

        if (!running) {
            running = true;
            audioThread = new Thread(this::listenLoop, "jarvis-audio");
            audioThread.start();
        }
        return START_STICKY;
    }

    private void startForegroundNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL_ID, "Escucha continua", NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("Jarvis escuchando en segundo plano");
            ((NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE))
                    .createNotificationChannel(ch);
        }
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open,
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0);
        Notification notif = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Jarvis")
                .setContentText("Escuchando — di \"Jarvis\"")
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else {
            startForeground(NOTIF_ID, notif);
        }
    }

    // ---- Bucle principal de escucha ----

    private void listenLoop() {
        fetchSettings();   // aplica la sensibilidad guardada en el panel
        int minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        int bufSize = Math.max(minBuf, SAMPLE_RATE); // ~1s de holgura
        AudioRecord recorder = null;
        boolean armed = false;

        while (running) {
            try {
                if (recorder == null) {
                    // VOICE_RECOGNITION: sin AGC agresivo, capta mejor la voz floja/susurro
                    // (VOICE_COMMUNICATION recortaba los susurros). Para cortar la voz de
                    // Jarvis esta el boton PARAR de la app.
                    recorder = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,
                            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                            AudioFormat.ENCODING_PCM_16BIT, bufSize);
                    if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
                        recorder.release(); recorder = null;
                        Thread.sleep(1500); continue;   // mic ocupado: reintentar
                    }
                    // Cancelacion de eco: para que el micro NO oiga la propia voz
                    // de Jarvis (permite decir "para" mientras habla)
                    try {
                        int sid = recorder.getAudioSessionId();
                        if (android.media.audiofx.AcousticEchoCanceler.isAvailable())
                            android.media.audiofx.AcousticEchoCanceler.create(sid).setEnabled(true);
                        if (android.media.audiofx.NoiseSuppressor.isAvailable())
                            android.media.audiofx.NoiseSuppressor.create(sid).setEnabled(true);
                    } catch (Exception ignored) {}
                    recorder.startRecording();
                }

                if (!pendingAudioJid.isEmpty()) armed = true;  // grabar el proximo segmento como audio
                if (armed) beep(660, 120);
                long noSpeech = armed ? (convMode ? NO_SPEECH_CONV_MS : NO_SPEECH_ARMED_MS)
                                      : NO_SPEECH_WAKE_MS;
                Segment seg = recordSegment(recorder, noSpeech);
                if (!running) break;

                if (seg == null || !seg.hadSpeech || seg.pcm.length < MIN_PCM_BYTES) {
                    if (!pendingAudioJid.isEmpty()) {   // esperaba un audio y no llego nada
                        pendingAudioJid = "";
                        armed = false;
                        speak("No he oido el audio, lo cancelo.");
                        waitTtsIdle(recorder);
                        continue;
                    }
                    if (armed) {
                        armed = false;
                        if (convMode) {                 // silencio: fin de la conversacion
                            convMode = false;
                            speak("Vale. Cuando quieras, dime Jarvis.");
                            waitTtsIdle(recorder);
                        } else {
                            beep(330, 200);             // no llego comando
                        }
                    }
                    continue;
                }

                if (!pendingAudioJid.isEmpty()) {       // el segmento grabado es el audio a enviar
                    String jid = pendingAudioJid;
                    pendingAudioJid = "";
                    armed = false;
                    sendWhatsAppAudio(jid, seg.pcm);
                    waitTtsIdle(recorder);
                    continue;
                }

                byte[] wav = wrapWav(seg.pcm);
                String text = safeTranscribe(wav);
                if (text == null || text.trim().isEmpty()) {
                    if (armed && !convMode) armed = false;
                    continue;
                }

                if (armed) {
                    armed = false;
                    if (convMode && isExitPhrase(text)) {   // "gracias/adios" -> salir
                        convMode = false;
                        speak("Hasta luego.");
                        waitTtsIdle(recorder);
                        continue;
                    }
                    beep(880, 120);
                    runCommandText(text);
                    if (convMode) armed = true;   // seguir hablando sin repetir "Jarvis"
                } else {
                    Wake wk = matchWake(text);
                    if (!wk.wake) { sendLog(text, "ignorado"); continue; }
                    if (!wk.command.isEmpty()) {
                        beep(880, 120);
                        runCommandText(wk.command);
                        if (convMode) armed = true;
                    } else {
                        sendLog(text, "armado");
                        armed = true;   // solo "Jarvis": esperar el comando
                    }
                }
                waitTtsIdle(recorder);
            } catch (Exception e) {
                try { if (recorder != null) { recorder.release(); recorder = null; } } catch (Exception ignored) {}
                try { Thread.sleep(1000); } catch (InterruptedException ignored) { break; }
            }
        }
        try { if (recorder != null) { recorder.stop(); recorder.release(); } } catch (Exception ignored) {}
    }

    private static class Segment { byte[] pcm; boolean hadSpeech; }

    /** Graba un segmento con VAD hasta silencio tras voz, o timeout sin voz. */
    private Segment recordSegment(AudioRecord recorder, long noSpeechMs) {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        short[] frame = new short[1600]; // ~100ms
        long t0 = System.currentTimeMillis();
        long silenceStart = 0;
        boolean hadSpeech = false;
        double noiseFloor = SILENCE_RMS;   // se calibra con el ambiente (o el eco en TTS)

        while (running) {
            int n = recorder.read(frame, 0, frame.length);
            if (n <= 0) continue;

            double sum = 0;
            for (int i = 0; i < n; i++) { double s = frame[i] / 32768.0; sum += s * s; }
            double rms = Math.sqrt(sum / n);

            // VAD sobre la senal cruda; el buffer guarda PCM crudo. La
            // amplificacion se hace al final, normalizando por pico (wrapWav).
            byte[] bytes = new byte[n * 2];
            for (int i = 0; i < n; i++) {
                bytes[i * 2] = (byte) (frame[i] & 0xff);
                bytes[i * 2 + 1] = (byte) ((frame[i] >> 8) & 0xff);
            }
            buf.write(bytes, 0, bytes.length);

            long ms = System.currentTimeMillis() - t0;

            // Calibra el suelo de ruido con los primeros frames (o con el eco de la
            // propia voz de Jarvis si esto corre durante el TTS).
            if (ms < MIN_SPEECH_MS) {
                noiseFloor = 0.8 * noiseFloor + 0.2 * rms;
                continue;
            }

            // Umbrales RELATIVOS al ruido: en sitio ruidoso suben solos (detecta la
            // voz por ENCIMA del ruido y arranca al instante); en silencio caen al
            // minimo (SILENCE_RMS = lo mas sensible que permita el panel).
            double startThr = Math.max(SILENCE_RMS, noiseFloor * SPEECH_MULT);
            double endThr = Math.max(SILENCE_RMS * 0.7, noiseFloor * 1.5);

            if (rms > startThr) {                    // voz clara sobre el ruido
                hadSpeech = true;
                silenceStart = 0;
            } else if (rms < endThr) {               // silencio / ruido de fondo
                noiseFloor = Math.min(NOISE_CAP, 0.95 * noiseFloor + 0.05 * rms);
                if (hadSpeech) {
                    if (silenceStart == 0) silenceStart = System.currentTimeMillis();
                    else if (System.currentTimeMillis() - silenceStart > SILENCE_MS) break;
                } else if (ms > noSpeechMs) {
                    break; // esperando "Jarvis" y nadie hablo: reciclar
                }
            } else {                                 // zona intermedia: mantener
                if (hadSpeech) silenceStart = 0;
                else if (ms > noSpeechMs) break;
            }
            if (ms > MAX_SEG_MS) break;
        }
        Segment seg = new Segment();
        seg.pcm = buf.toByteArray();
        seg.hadSpeech = hadSpeech;
        return seg;
    }

    // ---- Wake word ----

    private static class Wake { boolean wake; String command = ""; }

    private Wake matchWake(String text) {
        Wake r = new Wake();
        String norm = Normalizer.normalize(text.toLowerCase(Locale.ROOT), Normalizer.Form.NFD)
                .replaceAll("\\p{Mn}", "")
                .replaceAll("[^a-z0-9ñ ]+", " ")
                .trim();
        String[] w = norm.split("\\s+");
        // Escanea TODA la frase (no solo el principio): asi pilla "jarvis" aunque
        // lo digas en mitad de una conversacion, y coge lo que va detras como comando.
        int limit = w.length;
        for (int i = 0; i < limit; i++) {
            if (w[i].isEmpty()) continue;
            if (WAKE_RE.matcher(w[i]).matches()) {
                r.wake = true;
                r.command = join(w, i + 1);
                return r;
            }
            if (i + 1 < w.length && WAKE_RE.matcher(w[i] + w[i + 1]).matches()) {
                r.wake = true;
                r.command = join(w, i + 2);
                return r;
            }
        }
        return r;
    }

    private String join(String[] w, int from) {
        StringBuilder sb = new StringBuilder();
        for (int i = from; i < w.length; i++) { if (sb.length() > 0) sb.append(' '); sb.append(w[i]); }
        return sb.toString().trim();
    }

    // ---- Backend ----

    private String safeTranscribe(byte[] wav) {
        try { return transcribe(wav); }
        catch (Exception e) { return null; }
    }

    private String transcribe(byte[] wav) throws Exception {
        String boundary = "----jarvis" + System.currentTimeMillis();
        HttpURLConnection c = (HttpURLConnection) new URL(apiBase + "/api/transcribe").openConnection();
        c.setConnectTimeout(8000); c.setReadTimeout(20000);
        c.setDoOutput(true); c.setRequestMethod("POST");
        c.setRequestProperty("Authorization", "Bearer " + token);
        c.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
        DataOutputStream out = new DataOutputStream(c.getOutputStream());
        out.writeBytes("--" + boundary + "\r\n");
        out.writeBytes("Content-Disposition: form-data; name=\"audio\"; filename=\"audio.wav\"\r\n");
        out.writeBytes("Content-Type: audio/wav\r\n\r\n");
        out.write(wav);
        out.writeBytes("\r\n--" + boundary + "--\r\n");
        out.flush(); out.close();
        String body = readBody(c);
        return new JSONObject(body).optString("text", "");
    }

    /** Lee el texto de la pantalla del movil (accesibilidad), lo manda al backend
     *  para resumirlo con IA y lo dice. El backend guarda el contenido para preguntas. */
    private void readAndSummarizeScreen() {
        speak("Un momento, leo la pagina.");
        new Thread(() -> {
            try {
                String page = JarvisA11yService.dumpScreenText();
                if (page == null || page.trim().length() < 20) {
                    speak("No consigo leer esta pantalla. Comprueba que la accesibilidad de Jarvis esta activada.");
                    return;
                }
                HttpURLConnection c = (HttpURLConnection) new URL(apiBase + "/api/read_screen").openConnection();
                c.setConnectTimeout(8000); c.setReadTimeout(30000);
                c.setDoOutput(true); c.setRequestMethod("POST");
                c.setRequestProperty("Authorization", "Bearer " + token);
                c.setRequestProperty("Content-Type", "application/json");
                JSONObject payload = new JSONObject();
                payload.put("text", page);
                OutputStream out = c.getOutputStream();
                out.write(payload.toString().getBytes("UTF-8"));
                out.flush(); out.close();
                JSONObject resp = new JSONObject(readBody(c));
                String summary = resp.optString("summary", "");
                speak(summary.isEmpty() ? "No he podido resumir la pagina." : summary);
            } catch (Exception e) {
                speak("No he podido resumir la pagina.");
            }
        }).start();
    }

    /** "Analiza lo que veo": captura la pantalla por accesibilidad y la manda a la
     *  vision de la IA (tipo Google Lens). Recuerda el analisis para preguntas despues. */
    private void analyzeScreen() {
        if (!JarvisA11yService.isReady()) {
            speak("Activa la accesibilidad de Jarvis para poder analizar la pantalla.");
            return;
        }
        speak("Un momento, miro la pantalla.");
        JarvisA11yService.captureScreen((b64) -> {
            if (b64 == null || b64.length() < 100) {
                speak("No he podido capturar la pantalla.");
                return;
            }
            new Thread(() -> {
                try {
                    HttpURLConnection c = (HttpURLConnection) new URL(apiBase + "/api/vision").openConnection();
                    c.setConnectTimeout(8000); c.setReadTimeout(35000);
                    c.setDoOutput(true); c.setRequestMethod("POST");
                    c.setRequestProperty("Authorization", "Bearer " + token);
                    c.setRequestProperty("Content-Type", "application/json");
                    JSONObject payload = new JSONObject();
                    payload.put("image", b64);
                    payload.put("remember", true);
                    OutputStream out = c.getOutputStream();
                    out.write(payload.toString().getBytes("UTF-8"));
                    out.flush(); out.close();
                    JSONObject resp = new JSONObject(readBody(c));
                    String answer = resp.optString("answer", "");
                    speak(answer.isEmpty() ? "No he podido analizar la pantalla." : answer);
                } catch (Exception e) {
                    speak("No he podido analizar la pantalla.");
                }
            }).start();
        });
    }

    private void runCommandText(String text) {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(apiBase + "/api/command/text").openConnection();
            c.setConnectTimeout(8000); c.setReadTimeout(30000);
            c.setDoOutput(true); c.setRequestMethod("POST");
            c.setRequestProperty("Authorization", "Bearer " + token);
            c.setRequestProperty("Content-Type", "application/json");
            JSONObject payload = new JSONObject();
            payload.put("text", text); payload.put("platform", "mobile");
            OutputStream out = c.getOutputStream();
            out.write(payload.toString().getBytes("UTF-8"));
            out.flush(); out.close();
            JSONObject resp = new JSONObject(readBody(c));
            JSONObject result = resp.optJSONObject("result");
            JSONObject data = (result != null) ? result.optJSONObject("data") : null;
            if (data == null) {
                // No se pudo ejecutar (no reconocido, contacto sin numero...):
                // pitido de error + aviso por voz, en vez de callarse
                beep(330, 250);
                String msg = (result != null) ? result.optString("message", "") : "";
                if (msg.isEmpty()) {
                    JSONObject intent = resp.optJSONObject("intent");
                    if (intent != null) msg = intent.optString("error", "");
                }
                speak(msg.isEmpty() ? "No te he entendido" : msg);
                sendLog(text, "no reconocido");
                return;
            }
            String type = data.optString("type", "");
            if ("open_url".equals(type)) {
                launchUrl(data.optString("url", ""));
            } else if ("device_action".equals(type)) {
                if ("camera".equals(data.optString("action", ""))) launchUrl("camera");
            } else if ("spoken_response".equals(type)) {
                speak(data.optString("text", result.optString("message", "")),
                      data.optString("voice", ""));
            } else {
                String msg = result.optString("message", "");
                if (!msg.isEmpty() && msg.length() < 200) speak(msg);
            }
            sendLog(text, "ejecutado");
        } catch (Exception e) {
            beep(330, 250);
            speak("Ha habido un error de conexion");
            sendLog(text, "error de red");
        }
    }

    private String readBody(HttpURLConnection c) throws Exception {
        java.io.InputStream is = (c.getResponseCode() >= 400) ? c.getErrorStream() : c.getInputStream();
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] b = new byte[4096]; int r;
        while ((r = is.read(b)) != -1) bos.write(b, 0, r);
        is.close();
        return bos.toString("UTF-8");
    }

    // ---- Apertura de apps ----

    private void launchUrl(String url) {
        if (url == null || url.isEmpty()) return;
        // Alarmas/temporizadores: ponerlos en SILENCIO (SKIP_UI) directamente desde
        // el servicio. Abrir el reloj desde segundo plano lo bloquea ColorOS, pero
        // SET_ALARM con skip_ui lo crea sin abrir nada. Confirmamos por voz.
        if (url.startsWith("jarvis-alarm://") || url.startsWith("jarvis-timer://")) {
            setClock(url);
            return;
        }
        if (url.startsWith("jarvis-volume://")) {
            setVolume(url.substring("jarvis-volume://".length()));
            return;
        }
        if (url.startsWith("jarvis-ringer://")) {
            setRinger(url.substring("jarvis-ringer://".length()));
            return;
        }
        if (url.startsWith("jarvis-lock://")) {
            lockDevice();
            return;
        }
        if (url.startsWith("jarvis-torch://")) {
            setTorch(url.substring("jarvis-torch://".length()));
            return;
        }
        if (url.startsWith("jarvis-battery://")) {
            sayBattery();
            return;
        }
        if (url.startsWith("jarvis-findphone://")) {
            findPhone();
            return;
        }
        if (url.startsWith("jarvis-brightness://")) {
            setBrightness(url.substring("jarvis-brightness://".length()));
            return;
        }
        if (url.startsWith("jarvis-camera://")) {
            openCamera(url.substring("jarvis-camera://".length()));
            return;
        }
        if (url.startsWith("jarvis-bt://")) {
            setBluetooth(url.substring("jarvis-bt://".length()).startsWith("on"));
            return;
        }
        if (url.startsWith("jarvis-wifi://")) {
            try {
                Intent i = new Intent(android.provider.Settings.ACTION_WIFI_SETTINGS);
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                speak("Te abro los ajustes de wifi.");
            } catch (Exception ignored) {}
            return;
        }
        if (url.startsWith("jarvis-notif://")) {
            readNotifs();
            return;
        }
        if (url.startsWith("jarvis-termux://")) {
            handleTermux(url.substring("jarvis-termux://".length()));
            return;
        }
        if (url.startsWith("jarvis-music://")) {
            handleMusic(url.substring("jarvis-music://".length()));
            return;
        }
        if (url.startsWith("jarvis-readscreen://")) {
            readAndSummarizeScreen();
            return;
        }
        if (url.startsWith("jarvis-seescreen://")) {
            analyzeScreen();
            return;
        }
        if (url.startsWith("jarvis-loc://")) {
            getLocation();
            return;
        }
        if (url.startsWith("jarvis-vibrate://")) {
            vibratePhone();
            return;
        }
        if (url.startsWith("jarvis-wa-audio://")) {
            pendingAudioJid = url.substring("jarvis-wa-audio://".length()).replaceAll("[^0-9]", "");
            speak("Vale, dime el audio despues del pitido.");
            return;
        }
        if (url.startsWith("jarvis-car://")) {
            String arg = url.substring("jarvis-car://".length());
            if (arg.startsWith("learn")) learnCarBt();
            else setCarMode(arg.startsWith("on"));
            return;
        }
        if (url.startsWith("jarvis-callctl://")) {
            String arg = url.substring("jarvis-callctl://".length());
            if (arg.startsWith("answer")) answerCall();
            else rejectCall();
            return;
        }
        if (url.startsWith("jarvis-conv://")) {
            boolean on = url.substring("jarvis-conv://".length()).startsWith("on");
            convMode = on;
            speak(on ? "Modo conversacion activado. Dime." : "Vale, hasta luego.");
            return;
        }
        if (url.startsWith("jarvis-routine://")) {
            handleRoutine(url.substring("jarvis-routine://".length()));
            return;
        }
        // Auto-enviar WhatsApp: si abrimos un chat con texto ya escrito, arma el
        // servicio de accesibilidad para que pulse "Enviar" al cargar la conversacion.
        // (Requiere que el usuario tenga activado el servicio de accesibilidad de Jarvis.)
        String lu = url.toLowerCase();
        if ((lu.contains("whatsapp") || lu.contains("wa.me")) && lu.contains("text=")) {
            JarvisA11yService.armSend();
        }

        Intent t = new Intent(this, TrampolineActivity.class);
        t.putExtra("url", url);
        t.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS);
        try { startActivity(t); } catch (Exception ignored) {}
    }

    // ---- Grabador de rutinas (FASE 1 grabar, FASE 2 analizar, FASE 3 nombrar+reproducir) ----

    /** Controla el grabador de rutinas por voz:
     *  - "aprende esta rutina" / "graba una rutina"        -> record-start
     *  - "termina la rutina" / "guarda la rutina"           -> record-stop (nombre automatico)
     *  - "guarda la rutina como X" / "...y llamala X"       -> record-stop:X (con nombre)
     *  - "lista mis rutinas"                                -> list
     *  - "analiza mis rutinas" / "que hago mas repetido"    -> analyze (FASE 2)
     *  - "haz/ejecuta/reproduce la rutina X"                -> play:X (FASE 3)
     *  La captura y la reproduccion las hace JarvisA11yService; aqui solo se
     *  arma/desarma y se guarda/consulta/analiza lo grabado (RoutineRecorder),
     *  todo en el propio movil. */
    private void handleRoutine(String action) {
        if (!JarvisA11yService.isReady()) {
            speak("Necesito el servicio de accesibilidad Jarvis Gestos activado para las rutinas.");
            return;
        }
        if (action.startsWith("record-start")) {
            RoutineRecorder.startRecording();
            speak("Vale, grabando la rutina. Dime termina la rutina cuando acabes.");
        } else if (action.startsWith("record-stop")) {
            String name = null;
            int colon = action.indexOf(':');
            if (colon >= 0 && colon + 1 < action.length()) name = action.substring(colon + 1);
            int n = RoutineRecorder.stopRecording(this, name);
            String spokenName = name == null ? null : name.replace('_', ' ').trim();
            if (n <= 0) {
                speak("No he grabado ningun paso, no he guardado nada.");
            } else if (spokenName != null && !spokenName.isEmpty()) {
                speak("Rutina " + spokenName + " guardada con " + n + " " + (n == 1 ? "paso" : "pasos") + ".");
            } else {
                speak("Rutina guardada con " + n + " " + (n == 1 ? "paso" : "pasos") + ".");
            }
        } else if (action.startsWith("list")) {
            int n = RoutineRecorder.countRoutines(this);
            if (n <= 0) speak("Todavia no tienes ninguna rutina guardada.");
            else speak("Tienes " + n + " " + (n == 1 ? "rutina guardada" : "rutinas guardadas") + ".");
        } else if (action.startsWith("analyze")) {
            speak(RoutineRecorder.analyzeSpoken(this));
        } else if (action.startsWith("play:")) {
            String name = action.substring("play:".length());
            // La confirmacion ("Ejecutando..."/"No encuentro...") y el aviso
            // de fin la habla JarvisA11yService via routineAnnounce(), porque
            // la reproduccion corre en su propio hilo (puede tardar).
            JarvisA11yService.playRoutine(name);
        }
    }

    private void setVolume(String path) {
        try {
            // path = "music/up", "alarm/max", "ring/set:30"...
            String streamName = "music", act = path;
            int slash = path.indexOf('/');
            if (slash >= 0) { streamName = path.substring(0, slash); act = path.substring(slash + 1); }
            int stream = AudioManager.STREAM_MUSIC;
            if ("alarm".equals(streamName)) stream = AudioManager.STREAM_ALARM;
            else if ("ring".equals(streamName)) stream = AudioManager.STREAM_RING;
            else if ("notif".equals(streamName)) stream = AudioManager.STREAM_NOTIFICATION;

            AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            int max = am.getStreamMaxVolume(stream);
            int flag = AudioManager.FLAG_SHOW_UI;
            if ("up".equals(act)) {
                am.adjustStreamVolume(stream, AudioManager.ADJUST_RAISE, flag);
                am.adjustStreamVolume(stream, AudioManager.ADJUST_RAISE, flag);
            } else if ("down".equals(act)) {
                am.adjustStreamVolume(stream, AudioManager.ADJUST_LOWER, flag);
                am.adjustStreamVolume(stream, AudioManager.ADJUST_LOWER, flag);
            } else if ("max".equals(act)) {
                am.setStreamVolume(stream, max, flag);
            } else if ("mute".equals(act)) {
                am.setStreamVolume(stream, 0, flag);
            } else if (act.startsWith("set:")) {
                int pct = Integer.parseInt(act.substring(4));
                am.setStreamVolume(stream, Math.round(max * pct / 100f), flag);
            }
        } catch (Exception ignored) {}
    }

    /** Brillo de pantalla del sistema (0-255). Requiere permiso WRITE_SETTINGS. */
    private void setBrightness(String act) {
        try {
            if (!android.provider.Settings.System.canWrite(this)) {
                speak("Necesito permiso para cambiar el brillo. Te abro los ajustes, activalo.");
                Intent i = new Intent(android.provider.Settings.ACTION_MANAGE_WRITE_SETTINGS,
                        Uri.parse("package:" + getPackageName()));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                return;
            }
            android.content.ContentResolver cr = getContentResolver();
            android.provider.Settings.System.putInt(cr,
                    android.provider.Settings.System.SCREEN_BRIGHTNESS_MODE,
                    android.provider.Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL);
            int cur = android.provider.Settings.System.getInt(cr,
                    android.provider.Settings.System.SCREEN_BRIGHTNESS, 128);
            int val;
            if ("max".equals(act)) val = 255;
            else if ("min".equals(act)) val = 12;
            else if ("up".equals(act)) val = Math.min(255, cur + 45);
            else if ("down".equals(act)) val = Math.max(5, cur - 45);
            else if (act.startsWith("set:")) {
                int pct = Integer.parseInt(act.substring(4));
                val = Math.max(5, Math.round(255 * pct / 100f));
            } else return;
            android.provider.Settings.System.putInt(cr,
                    android.provider.Settings.System.SCREEN_BRIGHTNESS, val);
        } catch (Exception ignored) {}
    }

    /** Abre la camara: foto (still), video, o selfie (frontal si el fabricante lo respeta). */
    private void openCamera(String mode) {
        try {
            Intent i;
            if (mode.startsWith("video")) {
                i = new Intent(android.provider.MediaStore.INTENT_ACTION_VIDEO_CAMERA);
            } else {
                i = new Intent(android.provider.MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA);
                if (mode.startsWith("selfie")) {
                    i.putExtra("android.intent.extras.CAMERA_FACING", 1);
                    i.putExtra("android.intent.extras.LENS_FACING_FRONT", 1);
                    i.putExtra("android.intent.extra.USE_FRONT_CAMERA", true);
                }
            }
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
            // Auto-disparo (solo foto/selfie): accesibilidad pulsa el obturador
            if ((mode.startsWith("photo") || mode.startsWith("selfie")) && JarvisA11yService.isReady()) {
                JarvisA11yService.armShutter();
            }
        } catch (Exception e) {
            speak("No he podido abrir la camara.");
        }
    }

    /** Enciende/apaga el Bluetooth; si Android no deja (13+), abre los ajustes. */
    private void setBluetooth(boolean on) {
        try {
            android.bluetooth.BluetoothManager bm =
                    (android.bluetooth.BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
            android.bluetooth.BluetoothAdapter ad = bm != null ? bm.getAdapter()
                    : android.bluetooth.BluetoothAdapter.getDefaultAdapter();
            if (ad == null) { speak("Este movil no tiene bluetooth."); return; }
            boolean done = false;
            try {
                if (on && !ad.isEnabled()) done = ad.enable();
                else if (!on && ad.isEnabled()) done = ad.disable();
                else done = true;
            } catch (Exception ignored) {}
            if (done) {
                speak(on ? "Bluetooth encendido." : "Bluetooth apagado.");
            } else {
                Intent i = new Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS);
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                try { startActivity(i); } catch (Exception ignored) {}
                speak("Te abro los ajustes de bluetooth.");
            }
        } catch (Exception ignored) {}
    }

    /** Lee en alto las ultimas notificaciones que guardo el listener. */
    private void readNotifs() {
        java.util.List<String> ns = JarvisNotifService.getRecent();
        if (ns == null || ns.isEmpty()) {
            speak("No tienes notificaciones recientes, o falta activar el acceso a notificaciones.");
            return;
        }
        StringBuilder sb = new StringBuilder("Tus ultimas notificaciones. ");
        int n = 0;
        for (int k = ns.size() - 1; k >= 0 && n < 6; k--, n++) sb.append(ns.get(k)).append(". ");
        speak(sb.toString());
    }

    // ---- Integracion con Termux (Termux:API) ----
    private void runTermux(String bin, String[] args) {
        try {
            Intent i = new Intent();
            i.setClassName("com.termux", "com.termux.app.RunCommandService");
            i.setAction("com.termux.RUN_COMMAND");
            i.putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/" + bin);
            if (args != null) i.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", args);
            i.putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
            i.putExtra("com.termux.RUN_COMMAND_SESSION_ACTION", "0");
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(i);
            else startService(i);
        } catch (Exception e) {
            speak("No he podido usar Termux. Comprueba que esta instalado y permitido.");
        }
    }

    /** Igual que runTermux pero en PRIMER PLANO (sesion visible). La camara de
     *  termux-camera-photo NO captura en segundo plano, asi que la foto va por aqui. */
    private void runTermuxFg(String bin, String[] args) {
        try {
            Intent i = new Intent();
            i.setClassName("com.termux", "com.termux.app.RunCommandService");
            i.setAction("com.termux.RUN_COMMAND");
            i.putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/" + bin);
            if (args != null) i.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", args);
            i.putExtra("com.termux.RUN_COMMAND_BACKGROUND", false);
            i.putExtra("com.termux.RUN_COMMAND_SESSION_ACTION", "0");
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(i);
            else startService(i);
        } catch (Exception e) {
            speak("No he podido usar Termux. Comprueba que esta instalado y permitido.");
        }
    }

    /** Control de musica del movil: play/pause/next/prev (tecla multimedia a la app
     *  activa, sea Spotify, YouTube Music, etc.) o buscar y reproducir en Spotify. */
    private void handleMusic(String spec) {
        try {
            if (spec.startsWith("spotify?q=")) {
                String q = java.net.URLDecoder.decode(spec.substring("spotify?q=".length()), "UTF-8");
                try {
                    Intent i = new Intent(Intent.ACTION_VIEW,
                            android.net.Uri.parse("spotify:search:" + android.net.Uri.encode(q)));
                    i.setPackage("com.spotify.music");
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(i);
                } catch (Exception e) {
                    Intent w = new Intent(Intent.ACTION_VIEW, android.net.Uri.parse(
                            "https://open.spotify.com/search/" + android.net.Uri.encode(q)));
                    w.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(w);
                }
                speak("Buscando " + q + " en Spotify.");
                return;
            }
            int key;
            String say;
            switch (spec) {
                case "play":  key = android.view.KeyEvent.KEYCODE_MEDIA_PLAY;     say = "Dale."; break;
                case "pause": key = android.view.KeyEvent.KEYCODE_MEDIA_PAUSE;    say = "Pausado."; break;
                case "next":  key = android.view.KeyEvent.KEYCODE_MEDIA_NEXT;     say = "Siguiente."; break;
                case "prev":  key = android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS; say = "Anterior."; break;
                default:      key = android.view.KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE; say = "Hecho."; break;
            }
            sendMediaKey(key);
            speak(say);
        } catch (Exception e) {
            speak("No he podido controlar la musica.");
        }
    }

    private void sendMediaKey(int keycode) {
        try {
            android.media.AudioManager am = (android.media.AudioManager)
                    getSystemService(android.content.Context.AUDIO_SERVICE);
            long t = android.os.SystemClock.uptimeMillis();
            am.dispatchMediaKeyEvent(new android.view.KeyEvent(t, t,
                    android.view.KeyEvent.ACTION_DOWN, keycode, 0));
            am.dispatchMediaKeyEvent(new android.view.KeyEvent(t, t,
                    android.view.KeyEvent.ACTION_UP, keycode, 0));
        } catch (Exception ignored) {}
    }

    private void handleTermux(String spec) {
        try {
            if (spec.startsWith("photo:")) {
                String cam = spec.substring("photo:".length());
                // Script en el movil: captura (en primer plano) + sube a Immich por API.
                runTermuxFg("bash", new String[]{
                    "/data/data/com.termux/files/home/.jarvis/photo.sh", cam});
                speak("Hecho.");
            } else if (spec.startsWith("sms?")) {
                String q = spec.substring("sms?".length());
                String num = "", msg = "";
                for (String kv : q.split("&")) {
                    if (kv.startsWith("n=")) num = kv.substring(2);
                    else if (kv.startsWith("m=")) msg = java.net.URLDecoder.decode(kv.substring(2), "UTF-8");
                }
                if (!num.isEmpty()) {
                    runTermux("termux-sms-send", new String[]{"-n", num, msg});
                    speak("SMS enviado.");
                }
            } else if (spec.startsWith("clip?set=")) {
                String txt = java.net.URLDecoder.decode(spec.substring("clip?set=".length()), "UTF-8");
                runTermux("termux-clipboard-set", new String[]{txt});
                speak("Copiado en el movil.");
            } else if (spec.startsWith("recordstop")) {
                runTermux("termux-microphone-record", new String[]{"-q"});
                speak("Nota de voz guardada.");
            } else if (spec.startsWith("record")) {
                String path = "/sdcard/jarvis_nota_" + System.currentTimeMillis() + ".m4a";
                runTermux("termux-microphone-record", new String[]{"-f", path, "-l", "120"});
                speak("Grabando la nota de voz. Di, termina la nota, cuando acabes.");
            }
        } catch (Exception ignored) {}
    }

    /** "Donde estoy": ubicacion + direccion (Geocoder). Requiere permiso de ubicacion. */
    private void getLocation() {
        try {
            if (Build.VERSION.SDK_INT >= 23
                    && checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION)
                    != android.content.pm.PackageManager.PERMISSION_GRANTED
                    && checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION)
                    != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                speak("Necesito permiso de ubicacion. Activalo en Ajustes de Jarvis.");
                return;
            }
            android.location.LocationManager lm =
                    (android.location.LocationManager) getSystemService(Context.LOCATION_SERVICE);
            android.location.Location loc = null;
            for (String prov : new String[]{"gps", "network", "passive"}) {
                try {
                    android.location.Location l = lm.getLastKnownLocation(prov);
                    if (l != null && (loc == null || l.getTime() > loc.getTime())) loc = l;
                } catch (Exception ignored) {}
            }
            if (loc == null) { speak("No consigo tu ubicacion ahora mismo."); return; }
            String said = null;
            try {
                android.location.Geocoder gc = new android.location.Geocoder(this, new Locale("es"));
                java.util.List<android.location.Address> addrs =
                        gc.getFromLocation(loc.getLatitude(), loc.getLongitude(), 1);
                if (addrs != null && !addrs.isEmpty()) {
                    android.location.Address a = addrs.get(0);
                    StringBuilder sb = new StringBuilder("Estas en ");
                    if (a.getThoroughfare() != null) {
                        sb.append(a.getThoroughfare());
                        if (a.getSubThoroughfare() != null) sb.append(" ").append(a.getSubThoroughfare());
                        sb.append(", ");
                    }
                    if (a.getLocality() != null) sb.append(a.getLocality());
                    else if (a.getSubAdminArea() != null) sb.append(a.getSubAdminArea());
                    said = sb.toString();
                }
            } catch (Exception ignored) {}
            if (said == null) {
                said = String.format(Locale.ROOT, "Estas cerca de latitud %.4f, longitud %.4f",
                        loc.getLatitude(), loc.getLongitude());
            }
            speak(said);
        } catch (Exception e) {
            speak("No he podido obtener la ubicacion.");
        }
    }

    private void vibratePhone() {
        try {
            Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (v != null && v.hasVibrator()) {
                if (Build.VERSION.SDK_INT >= 26)
                    v.vibrate(VibrationEffect.createOneShot(600, VibrationEffect.DEFAULT_AMPLITUDE));
                else v.vibrate(600);
            }
        } catch (Exception ignored) {}
    }

    private void setRinger(String mode) {
        try {
            AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            // El silencio/vibracion necesita acceso a "No molestar" en Android 6+
            if ((mode.equals("silent") || mode.equals("vibrate"))
                    && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                    && nm != null && !nm.isNotificationPolicyAccessGranted()) {
                Intent i = new Intent(android.provider.Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS);
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                try { startActivity(i); } catch (Exception ignored) {}
                speak("Dale permiso a Jarvis para No molestar y vuelve a intentarlo");
                return;
            }
            int m = AudioManager.RINGER_MODE_NORMAL;
            String say = "Sonido activado";
            if (mode.equals("silent")) { m = AudioManager.RINGER_MODE_SILENT; say = "Modo silencio"; }
            else if (mode.equals("vibrate")) { m = AudioManager.RINGER_MODE_VIBRATE; say = "Modo vibracion"; }
            am.setRingerMode(m);
            speak(say);
        } catch (Exception e) {
            speak("No he podido cambiar el modo");
        }
    }

    private boolean torchOn = false;

    private void setTorch(String act) {
        try {
            CameraManager cm = (CameraManager) getSystemService(Context.CAMERA_SERVICE);
            String camId = null;
            for (String id : cm.getCameraIdList()) {
                Boolean has = cm.getCameraCharacteristics(id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
                Integer facing = cm.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING);
                if (Boolean.TRUE.equals(has)
                        && (facing == null || facing == CameraCharacteristics.LENS_FACING_BACK)) {
                    camId = id; break;
                }
            }
            if (camId == null) { speak("Este movil no tiene linterna"); return; }
            if ("sos".equals(act)) {
                final String fcam = camId;
                final CameraManager fcm = cm;
                new Thread(() -> {
                    // SOS en Morse: . . .  - - -  . . .  (repetido un par de veces)
                    int[] pat = {200, 200, 200, 600, 600, 600, 200, 200, 200};
                    try {
                        for (int rep = 0; rep < 3 && running; rep++) {
                            for (int d : pat) {
                                if (!running) break;
                                fcm.setTorchMode(fcam, true);
                                Thread.sleep(d);
                                fcm.setTorchMode(fcam, false);
                                Thread.sleep(200);
                            }
                            Thread.sleep(700);
                        }
                    } catch (Exception ignored) {}
                    try { fcm.setTorchMode(fcam, false); } catch (Exception ignored) {}
                    torchOn = false;
                }).start();
                return;
            }
            boolean target = "on".equals(act) || (!"off".equals(act) && !torchOn);
            cm.setTorchMode(camId, target);
            torchOn = target;
        } catch (Exception e) {
            speak("No he podido usar la linterna");
        }
    }

    private void sayBattery() {
        try {
            BatteryManager bm = (BatteryManager) getSystemService(Context.BATTERY_SERVICE);
            int pct = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
            speak("Tienes el " + pct + " por ciento de bateria");
        } catch (Exception e) {
            speak("No he podido leer la bateria");
        }
    }

    private void lockDevice() {
        try {
            DevicePolicyManager dpm = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
            ComponentName admin = new ComponentName(this, JarvisAdmin.class);
            if (dpm != null && dpm.isAdminActive(admin)) {
                dpm.lockNow();
            } else {
                Intent i = new Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN);
                i.putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, admin);
                i.putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION,
                        "Permite a Jarvis bloquear el movil por voz");
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                try { startActivity(i); } catch (Exception ignored) {}
                speak("Activa el permiso para que pueda bloquear el movil");
            }
        } catch (Exception ignored) {}
    }

    private void setClock(String url) {
        try {
            // Etiqueta opcional para recordatorios: jarvis-alarm://6:0?msg=comprar%20pan
            String msg = null;
            int q = url.indexOf("?msg=");
            if (q >= 0) {
                try { msg = java.net.URLDecoder.decode(url.substring(q + 5), "UTF-8"); } catch (Exception ignored) {}
                url = url.substring(0, q);
            }
            boolean hasMsg = msg != null && !msg.isEmpty();
            Intent intent;
            String confirm;
            if (url.startsWith("jarvis-alarm://")) {
                String[] hm = url.substring("jarvis-alarm://".length()).split(":");
                int h = Integer.parseInt(hm[0]);
                int m = hm.length > 1 ? Integer.parseInt(hm[1]) : 0;
                intent = new Intent(android.provider.AlarmClock.ACTION_SET_ALARM);
                intent.putExtra(android.provider.AlarmClock.EXTRA_HOUR, h);
                intent.putExtra(android.provider.AlarmClock.EXTRA_MINUTES, m);
                intent.putExtra(android.provider.AlarmClock.EXTRA_SKIP_UI, true);
                if (hasMsg) {
                    intent.putExtra(android.provider.AlarmClock.EXTRA_MESSAGE, msg);
                    confirm = String.format(Locale.ROOT, "Te lo recuerdo a las %d %02d: %s", h, m, msg);
                } else {
                    confirm = String.format(Locale.ROOT, "Alarma puesta a las %d %02d", h, m);
                }
            } else {
                int secs = Integer.parseInt(url.substring("jarvis-timer://".length()));
                intent = new Intent(android.provider.AlarmClock.ACTION_SET_TIMER);
                intent.putExtra(android.provider.AlarmClock.EXTRA_LENGTH, secs);
                intent.putExtra(android.provider.AlarmClock.EXTRA_SKIP_UI, true);
                int mins = secs / 60;
                if (hasMsg) {
                    intent.putExtra(android.provider.AlarmClock.EXTRA_MESSAGE, msg);
                    confirm = (mins > 0 ? "Te lo recuerdo en " + mins + " minutos: "
                                        : "Te lo recuerdo en " + secs + " segundos: ") + msg;
                } else {
                    confirm = mins > 0 ? "Temporizador de " + mins + " minutos" : "Temporizador de " + secs + " segundos";
                }
            }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
            speak(confirm);
        } catch (Exception e) {
            speak("No he podido poner la alarma");
        }
    }

    // ---- Utilidades ----

    /** Normaliza por pico: sube cada frase a un nivel fuerte y constante para
     *  Whisper (voz floja/lejana se amplifica mas), con tope anti-ruido. */
    private void normalize(byte[] pcm) {
        int maxAbs = 1;
        for (int i = 0; i + 1 < pcm.length; i += 2) {
            int s = (short) ((pcm[i] & 0xff) | (pcm[i + 1] << 8));
            int a = Math.abs(s);
            if (a > maxAbs) maxAbs = a;
        }
        float gain = (float) NORM_TARGET / maxAbs;
        if (gain > NORM_MAX_GAIN) gain = NORM_MAX_GAIN;
        if (gain <= 1.0f) return; // ya viene fuerte: no tocar
        for (int i = 0; i + 1 < pcm.length; i += 2) {
            int s = (short) ((pcm[i] & 0xff) | (pcm[i + 1] << 8));
            int v = (int) (s * gain);
            if (v > 32767) v = 32767; else if (v < -32768) v = -32768;
            pcm[i] = (byte) (v & 0xff);
            pcm[i + 1] = (byte) ((v >> 8) & 0xff);
        }
    }

    private byte[] wrapWav(byte[] pcm) {
        normalize(pcm);
        int len = pcm.length;
        int rate = SAMPLE_RATE, ch = 1, bits = 16;
        int byteRate = rate * ch * bits / 8;
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        try {
            o.write(new byte[]{'R','I','F','F'});
            writeInt(o, 36 + len);
            o.write(new byte[]{'W','A','V','E','f','m','t',' '});
            writeInt(o, 16); writeShort(o, 1); writeShort(o, ch);
            writeInt(o, rate); writeInt(o, byteRate);
            writeShort(o, ch * bits / 8); writeShort(o, bits);
            o.write(new byte[]{'d','a','t','a'});
            writeInt(o, len);
            o.write(pcm);
        } catch (Exception ignored) {}
        return o.toByteArray();
    }

    private void writeInt(ByteArrayOutputStream o, int v) {
        o.write(v & 0xff); o.write((v >> 8) & 0xff); o.write((v >> 16) & 0xff); o.write((v >> 24) & 0xff);
    }
    private void writeShort(ByteArrayOutputStream o, int v) { o.write(v & 0xff); o.write((v >> 8) & 0xff); }

    private void beep(int freqUnused, int ms) {
        try { if (tone != null) tone.startTone(ToneGenerator.TONE_PROP_BEEP, ms); } catch (Exception ignored) {}
    }

    private void speak(String text) { speak(text, null); }

    private void speak(String text, String voice) {
        if (text == null || text.isEmpty()) return;
        // Garantizar que se oiga: si el volumen multimedia esta silenciado o muy
        // bajo, subirlo a un nivel audible antes de hablar (si no, Jarvis "no habla")
        try {
            AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            int max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
            int cur = am.getStreamVolume(AudioManager.STREAM_MUSIC);
            if (cur < Math.max(1, max / 4)) {
                am.setStreamVolume(AudioManager.STREAM_MUSIC, Math.round(max * 0.5f), 0);
            }
        } catch (Exception ignored) {}
        // 1) Voz del servidor (masculina; voice!=null para traducciones en otro idioma).
        //    2) Si la red falla, TTS local.
        if (speakServer(text, voice)) return;
        if (tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis");
    }

    /** Reproduce la voz generada en el servidor (MP3 via /api/tts). true si arranco. */
    private boolean speakServer(String text, String voice) {
        if (apiBase == null || apiBase.isEmpty()) return false;
        stopPlayer();
        MediaPlayer mp = null;
        try {
            String url = apiBase + "/api/tts?text=" + URLEncoder.encode(text, "UTF-8");
            if (voice != null && !voice.isEmpty())
                url += "&voice=" + URLEncoder.encode(voice, "UTF-8");
            mp = new MediaPlayer();
            mp.setAudioStreamType(AudioManager.STREAM_MUSIC);
            mp.setDataSource(url);
            mp.setOnErrorListener((p, what, extra) -> true);
            mp.prepare();   // sincrono: si red/servidor fallan, lanza -> fallback TTS local
            ttsPlayer = mp;
            mp.start();
            return true;
        } catch (Exception e) {
            if (mp != null) { try { mp.release(); } catch (Exception ignored) {} }
            ttsPlayer = null;
            return false;
        }
    }

    private volatile Ringtone findRingtone;   // tono de "encuentra mi movil"

    /** Hace sonar el movil a tope (aunque este en silencio) + vibra + parpadea la
     *  linterna durante ~10s. Se dispara con "Jarvis, donde estas / busca el movil". */
    private void findPhone() {
        speak("Aqui estoy, jefe.");
        try {
            final AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            final int oldVol = am.getStreamVolume(AudioManager.STREAM_ALARM);
            try { am.setStreamVolume(AudioManager.STREAM_ALARM,
                    am.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0); } catch (Exception ignored) {}

            Uri alarmUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
            if (alarmUri == null) alarmUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
            Ringtone rt = RingtoneManager.getRingtone(getApplicationContext(), alarmUri);
            if (rt != null) {
                try {
                    rt.setAudioAttributes(new android.media.AudioAttributes.Builder()
                            .setUsage(android.media.AudioAttributes.USAGE_ALARM)
                            .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION)
                            .build());
                } catch (Exception ignored) {}
                findRingtone = rt;
                try { rt.play(); } catch (Exception ignored) {}
            }

            Vibrator vib = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (vib != null && vib.hasVibrator()) {
                long[] pat = {0, 600, 300, 600, 300, 600, 300, 600, 300};
                try {
                    if (Build.VERSION.SDK_INT >= 26) vib.vibrate(VibrationEffect.createWaveform(pat, -1));
                    else vib.vibrate(pat, -1);
                } catch (Exception ignored) {}
            }

            // Parpadeo de linterna y, al cabo de ~10s, apagar todo y restaurar volumen
            new Thread(() -> {
                long end = System.currentTimeMillis() + 10000;
                boolean on = false;
                while (System.currentTimeMillis() < end && running && findRingtone != null) {
                    on = !on;
                    try { setTorch(on ? "on" : "off"); } catch (Exception ignored) {}
                    try { Thread.sleep(500); } catch (InterruptedException e) { break; }
                }
                try { setTorch("off"); } catch (Exception ignored) {}
                stopFindPhone();
                try { am.setStreamVolume(AudioManager.STREAM_ALARM, oldVol, 0); } catch (Exception ignored) {}
            }).start();
        } catch (Exception ignored) {}
    }

    private void stopFindPhone() {
        Ringtone r = findRingtone;
        findRingtone = null;
        try { if (r != null && r.isPlaying()) r.stop(); } catch (Exception ignored) {}
    }

    // ---- Audio de WhatsApp ----
    /** Guarda el PCM grabado como WAV, lo adjunta al chat de WhatsApp del numero
     *  (via extra "jid") y arma el auto-envio para que accesibilidad pulse "Enviar". */
    private void sendWhatsAppAudio(String jid, byte[] pcm) {
        try {
            byte[] wav = wrapWav(pcm);
            File f = new File(getCacheDir(), "jarvis_audio.wav");
            FileOutputStream fos = new FileOutputStream(f);
            fos.write(wav);
            fos.close();

            Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", f);
            speak("Enviando el audio.");
            JarvisA11yService.armSend();   // pulsa "Enviar" en la vista previa del adjunto

            Intent send = new Intent(Intent.ACTION_SEND);
            send.setType("audio/*");
            send.putExtra(Intent.EXTRA_STREAM, uri);
            send.putExtra("jid", jid + "@s.whatsapp.net");   // abre directo en ese chat
            send.setPackage("com.whatsapp");
            send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(send);
        } catch (Exception e) {
            speak("No he podido enviar el audio.");
        }
    }

    // ---- Modo coche ----
    private void setCarMode(boolean on) {
        carMode = on;
        try {
            AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            if (on) {
                carOldMusicVol = am.getStreamVolume(AudioManager.STREAM_MUSIC);
                am.setStreamVolume(AudioManager.STREAM_MUSIC,
                        am.getStreamMaxVolume(AudioManager.STREAM_MUSIC), 0);
            } else if (carOldMusicVol >= 0) {
                am.setStreamVolume(AudioManager.STREAM_MUSIC, carOldMusicVol, 0);
                carOldMusicVol = -1;
            }
        } catch (Exception ignored) {}

        if (on) {
            if (notifAccessEnabled()) {
                speak("Modo coche activado. Te leo los mensajes que lleguen.");
            } else {
                speak("Modo coche activado. Para leerte los mensajes, activa el acceso a notificaciones de Jarvis.");
                try {
                    Intent i = new Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS");
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(i);
                } catch (Exception ignored) {}
            }
        } else {
            speak("Modo coche desactivado.");
        }
    }

    private boolean notifAccessEnabled() {
        try {
            String flat = android.provider.Settings.Secure.getString(
                    getContentResolver(), "enabled_notification_listeners");
            return flat != null && flat.contains(getPackageName());
        } catch (Exception e) { return false; }
    }

    // ---- Auto-modo-coche por Bluetooth ----
    private void registerBtReceiver() {
        try {
            btReceiver = new BroadcastReceiver() {
                @Override public void onReceive(Context c, Intent i) {
                    try {
                        BluetoothDevice dev = i.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE);
                        if (dev == null) return;
                        String addr = dev.getAddress();
                        String act = i.getAction();
                        String carAddr = getSharedPreferences("jarvis", MODE_PRIVATE).getString("car_bt", "");
                        if (BluetoothDevice.ACTION_ACL_CONNECTED.equals(act)) {
                            lastBtAddr = addr;
                            if (!carAddr.isEmpty() && carAddr.equals(addr) && !carMode) setCarMode(true);
                        } else if (BluetoothDevice.ACTION_ACL_DISCONNECTED.equals(act)) {
                            if (!carAddr.isEmpty() && carAddr.equals(addr) && carMode) setCarMode(false);
                        }
                    } catch (Exception ignored) {}
                }
            };
            IntentFilter f = new IntentFilter();
            f.addAction(BluetoothDevice.ACTION_ACL_CONNECTED);
            f.addAction(BluetoothDevice.ACTION_ACL_DISCONNECTED);
            registerReceiver(btReceiver, f);
        } catch (Exception ignored) {}
    }

    private void learnCarBt() {
        if (lastBtAddr == null || lastBtAddr.isEmpty()) {
            speak("No detecto ningun bluetooth conectado. Conectate al del coche y dimelo.");
            return;
        }
        getSharedPreferences("jarvis", MODE_PRIVATE).edit().putString("car_bt", lastBtAddr).apply();
        speak("Vale, memorizado. Activare el modo coche cuando se conecte este bluetooth.");
    }

    // ---- Manos libres de llamadas ----
    private void answerCall() {
        try {
            android.telecom.TelecomManager tm =
                    (android.telecom.TelecomManager) getSystemService(Context.TELECOM_SERVICE);
            if (tm != null && Build.VERSION.SDK_INT >= 26) tm.acceptRingingCall();
        } catch (Exception e) {
            speak("No he podido contestar. Revisa el permiso de llamadas.");
        }
    }

    private void rejectCall() {
        try {
            android.telecom.TelecomManager tm =
                    (android.telecom.TelecomManager) getSystemService(Context.TELECOM_SERVICE);
            if (tm != null && Build.VERSION.SDK_INT >= 28) tm.endCall();
        } catch (Exception ignored) {}
    }

    /** El NotificationListener llama aqui para leer un mensaje en alto (solo en modo coche). */
    public static void carAnnounce(String text) {
        ListeningService s = self;
        if (s != null && s.carMode) s.speak(text);
    }
    public static boolean isCarMode() {
        ListeningService s = self;
        return s != null && s.carMode;
    }

    /** Lee los ajustes del backend (GET /api/settings) y aplica la sensibilidad. */
    private void fetchSettings() {
        if (apiBase == null || apiBase.isEmpty()) return;
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(apiBase + "/api/settings").openConnection();
            c.setConnectTimeout(4000);
            c.setReadTimeout(4000);
            c.setRequestProperty("User-Agent", "Jarvis");
            if (c.getResponseCode() != 200) return;
            String json = readBody(c);
            JSONObject o = new JSONObject(json);
            if (o.has("silence_rms"))   SILENCE_RMS   = o.getDouble("silence_rms");
            if (o.has("speech_mult"))   SPEECH_MULT   = o.getDouble("speech_mult");
            if (o.has("silence_ms"))    SILENCE_MS    = o.getLong("silence_ms");
            if (o.has("norm_max_gain")) NORM_MAX_GAIN = (float) o.getDouble("norm_max_gain");
            if (o.has("min_speech_ms")) MIN_SPEECH_MS = o.getLong("min_speech_ms");
        } catch (Exception ignored) {}
    }

    /** Recarga los ajustes en caliente (lo llama el panel tras guardar). */
    public static void reloadSettings() {
        ListeningService s = self;
        if (s != null) new Thread(s::fetchSettings).start();
    }

    /** Corta la voz de Jarvis al instante (lo llama el boton PARAR de la app). */
    public static void stopSpeakingExternal() {
        ListeningService s = self;
        if (s != null) s.stopSpeaking();
    }

    /** Sale del modo conversacion desde la app (boton MODO NORMAL). */
    public static void exitConvExternal() {
        ListeningService s = self;
        if (s != null) { s.convMode = false; s.stopSpeaking(); }
    }

    /** Para que JarvisA11yService pueda hablar el resultado de reproducir una
     *  rutina (FASE 3) desde su propio hilo de reproduccion, sin acoplarse a
     *  ListeningService mas alla de esta unica via (mismo patron que
     *  carAnnounce() para el modo coche). */
    public static void routineAnnounce(String text) {
        ListeningService s = self;
        if (s != null) s.speak(text);
    }

    private void stopPlayer() {
        MediaPlayer p = ttsPlayer;
        ttsPlayer = null;
        if (p != null) {
            try { p.stop(); } catch (Exception ignored) {}
            try { p.release(); } catch (Exception ignored) {}
        }
    }

    /** true si Jarvis esta hablando ahora (voz de servidor o TTS local). */
    private boolean ttsBusy() {
        try { MediaPlayer p = ttsPlayer; if (p != null && p.isPlaying()) return true; } catch (Exception ignored) {}
        try { if (tts != null && tts.isSpeaking()) return true; } catch (Exception ignored) {}
        try { Ringtone r = findRingtone; if (r != null && r.isPlaying()) return true; } catch (Exception ignored) {}
        return false;
    }

    private void stopSpeaking() {
        stopPlayer();
        stopFindPhone();
        try { if (tts != null) tts.stop(); } catch (Exception ignored) {}
    }

    private static final Pattern STOP_RE = Pattern.compile(
            "\\b(para|parate|para ya|calla|callate|calla ya|basta|ya basta|silencio|stop|"
            + "ya esta|vale ya|ya vale|dejalo|deja de hablar|para de hablar|no sigas|corta|"
            + "quieto|chiss?|shh?|no|espera|esperate|oye|perdona|perdon|alto|momento|"
            + "eso no|asi no|para para)\\b");

    /** Espera a que el TTS acabe, pero escuchando por si dices "para" para cortarlo. */
    /** Mientras Jarvis habla: la ENERGIA (hablas por encima de su eco) solo dispara
     *  la escucha; luego TRANSCRIBE y corta unicamente si era voz real (una palabra).
     *  Asi no corta con ruido/eco fantasma, solo si de verdad dices algo. */
    private void waitTtsIdle(AudioRecord recorder) {
        long t0 = System.currentTimeMillis();
        try {
            Thread.sleep(200);              // deja arrancar el TTS
            short[] frame = new short[1600]; // ~100ms
            double echo = 0;                 // PICO del eco de la voz de Jarvis
            int calib = 0;
            long loudStart = 0;
            while (running && ttsBusy() && System.currentTimeMillis() - t0 < 30000) {
                int n = recorder.read(frame, 0, frame.length);
                if (n <= 0) continue;
                double sum = 0;
                for (int i = 0; i < n; i++) { double s = frame[i] / 32768.0; sum += s * s; }
                double rms = Math.sqrt(sum / n);

                if (calib < 6) {             // ~600ms: toma el pico del eco de Jarvis
                    echo = Math.max(echo, rms);
                    calib++;
                    continue;
                }
                echo = Math.max(echo * 0.999, Math.min(rms, echo));
                double barge = Math.max(echo * 2.2, 0.02);   // claramente por encima del eco

                if (rms > barge) {
                    if (loudStart == 0) loudStart = System.currentTimeMillis();
                    else if (System.currentTimeMillis() - loudStart > 120) {
                        // Algo suena por encima de Jarvis: capturar y CONFIRMAR que
                        // es una orden de parada corta (no su propia voz ni ruido)
                        String said = bargeStopPhrase(recorder, frame);
                        if (said != null) {
                            stopSpeaking();
                            sendLog(said, "detenido");
                            break;
                        }
                        loudStart = 0;       // era ruido/eco/su voz: seguir hablando
                    }
                } else {
                    loudStart = 0;
                }
            }
        } catch (InterruptedException ignored) {}
    }

    /** Graba ~1s y devuelve el texto SOLO si es una orden de parada corta ("para",
     *  "no", "espera"...). Devuelve null si es su propia voz (frase larga), ruido o
     *  vacio -> asi Jarvis NO se para a si mismo. */
    private String bargeStopPhrase(AudioRecord recorder, short[] frame) {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        long t0 = System.currentTimeMillis();
        while (running && System.currentTimeMillis() - t0 < 1000) {
            int n = recorder.read(frame, 0, frame.length);
            if (n <= 0) continue;
            byte[] b = new byte[n * 2];
            for (int i = 0; i < n; i++) {
                b[i * 2] = (byte) (frame[i] & 0xff);
                b[i * 2 + 1] = (byte) ((frame[i] >> 8) & 0xff);
            }
            buf.write(b, 0, b.length);
        }
        byte[] pcm = buf.toByteArray();
        if (pcm.length < MIN_PCM_BYTES) return null;
        String t = safeTranscribe(wrapWav(pcm));
        if (t == null) return null;
        String norm = Normalizer.normalize(t.toLowerCase(Locale.ROOT), Normalizer.Form.NFD)
                .replaceAll("\\p{Mn}", "").trim();
        if (norm.isEmpty()) return null;
        int words = norm.split("\\s+").length;
        return (words <= 5 && STOP_RE.matcher(norm).find()) ? t : null;
    }

    private void sendLog(String text, String status) {
        BackgroundListeningPlugin.sendLog(text, status);
    }

    @Override
    public void onDestroy() {
        running = false;
        if (self == this) self = null;
        if (btReceiver != null) { try { unregisterReceiver(btReceiver); } catch (Exception ignored) {} }
        if (audioThread != null) audioThread.interrupt();
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        stopPlayer();
        if (tts != null) { tts.shutdown(); tts = null; }
        if (tone != null) { tone.release(); tone = null; }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
