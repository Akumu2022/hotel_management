plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ke.chakula.till"
    compileSdk = 36

    defaultConfig {
        applicationId = "ke.chakula.till"
        minSdk = 26 // Android 8.0
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        // Prefilled server address on the pairing screen; editable there.
        buildConfigField("String", "DEFAULT_SERVER", "\"${project.findProperty("chakulaServer") ?: ""}\"")
    }

    buildTypes {
        debug {
            // Development: allow plain http to a laptop on the same Wi-Fi.
            manifestPlaceholders["cleartext"] = "true"
        }
        release {
            isMinifyEnabled = false
            manifestPlaceholders["cleartext"] = "false"
            signingConfig = signingConfigs.getByName("debug") // replace with the real key before the pilot
        }
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

dependencies {
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    implementation("androidx.core:core-ktx:1.13.1")
}
