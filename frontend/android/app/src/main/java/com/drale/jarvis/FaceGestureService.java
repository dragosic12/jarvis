package com.drale.jarvis;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.media.AudioManager;
import android.os.Build;
import android.os.SystemClock;

import androidx.annotation.NonNull;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.LifecycleService;

import com.google.common.util.concurrent.ListenableFuture;
import com.google.mediapipe.framework.image.BitmapImageBuilder;
import com.google.mediapipe.framework.image.MPImage;
import com.google.mediapipe.tasks.components.containers.Category;
import com.google.mediapipe.tasks.core.BaseOptions;
import com.google.mediapipe.tasks.vision.core.ImageProcessingOptions;
import com.google.mediapipe.tasks.vision.core.RunningMode;
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarker;
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarkerResult;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * BOSS FINAL: control del movil con la cara.
 * Foreground service tipo camara (funciona con otras apps en primer plano) ->
 * MediaPipe Face Landmarker nativo detecta gestos -> JarvisA11yService ejecuta
 * la accion del sistema (atras, inicio, recientes, abrir app...).
 */
public class FaceGestureService extends LifecycleService {

    private static final String CH = "jarvis_gestos";
    // Apps de "feed" (scroll vertical): ahi mirar arriba/abajo hace scroll; en el
    // resto de apps mirar arriba/abajo sube/baja el volumen.
    private static final java.util.Set<String> FEED_APPS = new java.util.HashSet<>(java.util.Arrays.asList(
            "com.zhiliaoapp.musically", "com.ss.android.ugc.trill", "com.zhiliaoapp.musically.go",
            "com.instagram.android", "com.google.android.youtube", "com.twitter.android",
            "com.reddit.frontpage", "com.facebook.katana"));

    private FaceLandmarker landmarker;
    private ExecutorService exec;
    private ProcessCameraProvider provider;
    private AudioManager audio;
    private final Map<String, long[]> gate = new HashMap<>(); // gesto -> [armado, ultimoMs]

    @Override
    public void onCreate() {
        super.onCreate();
        audio = (AudioManager) getSystemService(AUDIO_SERVICE);
        startForegroundCam();
        try {
            setupLandmarker();
            startCamera();
        } catch (Exception e) {
            stopSelf();
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        super.onStartCommand(intent, flags, startId);
        return START_STICKY;
    }

    private void startForegroundCam() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(CH,
                    "Control por gestos", NotificationManager.IMPORTANCE_LOW));
        }
        Notification n = new NotificationCompat.Builder(this, CH)
                .setContentTitle("Jarvis · control por gestos")
                .setContentText("Controlando el movil con la cara")
                .setSmallIcon(android.R.drawable.ic_menu_camera)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(42, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA);
        } else {
            startForeground(42, n);
        }
    }

    private void setupLandmarker() {
        BaseOptions base = BaseOptions.builder().setModelAssetPath("face_landmarker.task").build();
        FaceLandmarker.FaceLandmarkerOptions opts = FaceLandmarker.FaceLandmarkerOptions.builder()
                .setBaseOptions(base)
                .setRunningMode(RunningMode.LIVE_STREAM)
                .setNumFaces(1)
                .setOutputFaceBlendshapes(true)
                .setResultListener(this::onResult)
                .setErrorListener(e -> { })
                .build();
        landmarker = FaceLandmarker.createFromOptions(this, opts);
    }

    private void startCamera() {
        exec = Executors.newSingleThreadExecutor();
        final ListenableFuture<ProcessCameraProvider> fut = ProcessCameraProvider.getInstance(this);
        fut.addListener(() -> {
            try {
                provider = fut.get();
                ImageAnalysis analysis = new ImageAnalysis.Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                        .build();
                analysis.setAnalyzer(exec, this::analyze);
                CameraSelector sel = new CameraSelector.Builder()
                        .requireLensFacing(CameraSelector.LENS_FACING_FRONT).build();
                provider.unbindAll();
                provider.bindToLifecycle(this, sel, analysis);
            } catch (Exception e) {
                stopSelf();
            }
        }, ContextCompat.getMainExecutor(this));
    }

    private void analyze(@NonNull ImageProxy image) {
        try {
            Bitmap bm = image.toBitmap();
            int rot = image.getImageInfo().getRotationDegrees();
            MPImage mp = new BitmapImageBuilder(bm).build();
            ImageProcessingOptions ipo = ImageProcessingOptions.builder().setRotationDegrees(rot).build();
            landmarker.detectAsync(mp, ipo, SystemClock.uptimeMillis());
        } catch (Exception ignored) {
        } finally {
            image.close();
        }
    }

    private void onResult(FaceLandmarkerResult result, MPImage input) {
        List<List<Category>> bs;
        try {
            if (result == null || !result.faceBlendshapes().isPresent()) return;
            bs = result.faceBlendshapes().get();
        } catch (Exception e) {
            return;
        }
        if (bs.isEmpty()) return;
        Map<String, Float> m = new HashMap<>();
        for (Category c : bs.get(0)) m.put(c.categoryName(), c.score());

        // 'browInnerUp' es la señal fuerte de "levantar cejas" (sorpresa); antes usaba
        // solo browOuterUp y por eso no lo pillaba.
        float cejas  = Math.max(get(m, "browInnerUp"), avg(m, "browOuterUpLeft", "browOuterUpRight"));
        float ceno   = avg(m, "browDownLeft", "browDownRight");
        float boca   = get(m, "jawOpen");
        float sonr   = avg(m, "mouthSmileLeft", "mouthSmileRight");
        float der    = avg(m, "eyeLookInLeft", "eyeLookOutRight");
        float izq    = avg(m, "eyeLookOutLeft", "eyeLookInRight");
        float arriba = avg(m, "eyeLookUpLeft", "eyeLookUpRight");
        float abajo  = avg(m, "eyeLookDownLeft", "eyeLookDownRight");
        boolean feed = FEED_APPS.contains(JarvisA11yService.currentPackage());

        // Miradas primero (direccionales), luego gestos de cara. Uno por vez.
        if      (fire("arriba", arriba, 0.55f)) { if (feed) JarvisA11yService.swipe(false); else vol(true); }   // arriba: feed=anterior / subir volumen
        else if (fire("abajo",  abajo,  0.55f)) { if (feed) JarvisA11yService.swipe(true);  else vol(false); }  // abajo:  feed=siguiente / bajar volumen
        else if (fire("der",    der,    0.50f)) JarvisA11yService.recents();                                    // mirar derecha -> cambiar de app
        else if (fire("izq",    izq,    0.50f)) JarvisA11yService.home();                                       // mirar izquierda -> inicio
        else if (fire("cejas",  cejas,  0.42f)) JarvisA11yService.back();                                       // cejas -> atras
        else if (fire("ceno",   ceno,   0.45f)) JarvisA11yService.notifications();                              // ceño -> notificaciones
        else if (fire("boca",   boca,   0.55f)) JarvisA11yService.launch("com.whatsapp");                       // boca -> abrir WhatsApp
        else if (fire("sonrisa",sonr,   0.60f)) JarvisA11yService.launch("com.google.android.youtube");         // sonrisa -> YouTube
    }

    private boolean fire(String name, float v, float th) {
        long[] g = gate.get(name);
        if (g == null) { g = new long[]{1, 0}; gate.put(name, g); }
        long now = SystemClock.uptimeMillis();
        if (v < th * 0.6f) g[0] = 1;                         // rearmar al bajar del umbral
        if (v >= th && g[0] == 1 && now - g[1] > 1400) {     // umbral + rearmado + cooldown 1.4s
            g[0] = 0; g[1] = now;
            return true;
        }
        return false;
    }

    private void vol(boolean up) {
        try {
            audio.adjustStreamVolume(AudioManager.STREAM_MUSIC,
                    up ? AudioManager.ADJUST_RAISE : AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI);
        } catch (Exception ignored) {}
    }

    private static float get(Map<String, Float> m, String k) { Float f = m.get(k); return f == null ? 0f : f; }
    private static float avg(Map<String, Float> m, String a, String b) { return (get(m, a) + get(m, b)) / 2f; }

    @Override
    public void onDestroy() {
        try { if (provider != null) provider.unbindAll(); } catch (Exception ignored) {}
        try { if (landmarker != null) landmarker.close(); } catch (Exception ignored) {}
        try { if (exec != null) exec.shutdown(); } catch (Exception ignored) {}
        super.onDestroy();
    }
}
