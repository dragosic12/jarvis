package com.drale.jarvis;

import android.Manifest;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

/** Puente JS <-> servicio de escucha nativo. */
@CapacitorPlugin(
    name = "BackgroundListening",
    permissions = { @Permission(strings = { Manifest.permission.CAMERA }, alias = "camera") }
)
public class BackgroundListeningPlugin extends Plugin {

    private static BackgroundListeningPlugin instance;

    @Override
    public void load() {
        instance = this;
    }

    /** Llamado desde el servicio (hilo de audio) para reflejar lo oido en la UI web. */
    public static void sendLog(String text, String status) {
        if (instance == null) return;
        JSObject data = new JSObject();
        data.put("text", text);
        data.put("status", status);
        instance.notifyListeners("log", data);
    }

    @PluginMethod
    public void start(PluginCall call) {
        Intent intent = new Intent(getContext(), ListeningService.class);
        intent.putExtra("apiBase", call.getString("apiBase", ""));
        intent.putExtra("token", call.getString("token", ""));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getContext().startForegroundService(intent);
        } else {
            getContext().startService(intent);
        }
        call.resolve();
    }

    @PluginMethod
    public void stop(PluginCall call) {
        getContext().stopService(new Intent(getContext(), ListeningService.class));
        call.resolve();
    }

    /** Recarga los ajustes (sensibilidad) sin reiniciar la escucha. */
    @PluginMethod
    public void reloadSettings(PluginCall call) {
        ListeningService.reloadSettings();
        call.resolve();
    }

    /** Corta la voz de Jarvis (boton PARAR). */
    @PluginMethod
    public void stopSpeaking(PluginCall call) {
        ListeningService.stopSpeakingExternal();
        call.resolve();
    }

    /** Abre una URL desde primer plano cuando la escucha la maneja el WebView. */
    @PluginMethod
    public void openUrl(PluginCall call) {
        String url = call.getString("url");
        if (url == null || url.isEmpty()) { call.reject("url requerida"); return; }
        Intent intent = new Intent(getContext(), TrampolineActivity.class);
        intent.putExtra("url", url);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS);
        getContext().startActivity(intent);
        call.resolve();
    }

    /** Pide el permiso de camara (para el modo gestos del WebView). */
    @PluginMethod
    public void requestCamera(PluginCall call) {
        if (getPermissionState("camera") == PermissionState.GRANTED) {
            JSObject r = new JSObject(); r.put("granted", true); call.resolve(r);
        } else {
            requestPermissionForAlias("camera", call, "onCameraPerm");
        }
    }

    @PermissionCallback
    private void onCameraPerm(PluginCall call) {
        JSObject r = new JSObject();
        r.put("granted", getPermissionState("camera") == PermissionState.GRANTED);
        call.resolve(r);
    }

    @PluginMethod
    public void ensureOverlayPermission(PluginCall call) {
        boolean granted = Build.VERSION.SDK_INT < Build.VERSION_CODES.M
                || Settings.canDrawOverlays(getContext());
        if (!granted) {
            Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getContext().getPackageName()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
        }
        JSObject ret = new JSObject();
        ret.put("granted", granted);
        call.resolve(ret);
    }

    @PluginMethod
    public void ensureBatteryUnrestricted(PluginCall call) {
        PowerManager pm = (PowerManager) getContext().getSystemService(Context.POWER_SERVICE);
        boolean granted = pm != null && pm.isIgnoringBatteryOptimizations(getContext().getPackageName());
        if (!granted) {
            Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:" + getContext().getPackageName()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
        }
        JSObject ret = new JSObject();
        ret.put("granted", granted);
        call.resolve(ret);
    }

    // ---- Control por gestos faciales (boss final) ----

    /** ¿Está activado el Servicio de Accesibilidad de Jarvis? */
    @PluginMethod
    public void isAccessibilityEnabled(PluginCall call) {
        String flat = new ComponentName(getContext(), JarvisA11yService.class).flattenToString();
        String enabled = Settings.Secure.getString(getContext().getContentResolver(),
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        JSObject r = new JSObject();
        r.put("enabled", enabled != null && enabled.contains(flat));
        call.resolve(r);
    }

    @PluginMethod
    public void openAccessibilitySettings(PluginCall call) {
        Intent i = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getContext().startActivity(i);
        call.resolve();
    }

    @PluginMethod
    public void startFaceControl(PluginCall call) {
        Intent i = new Intent(getContext(), FaceGestureService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getContext().startForegroundService(i);
        } else {
            getContext().startService(i);
        }
        call.resolve();
    }

    @PluginMethod
    public void stopFaceControl(PluginCall call) {
        getContext().stopService(new Intent(getContext(), FaceGestureService.class));
        call.resolve();
    }
}
