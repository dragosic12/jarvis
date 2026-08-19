package com.drale.jarvis;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(BackgroundListeningPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
