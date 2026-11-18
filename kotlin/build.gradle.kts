// SPDX-License-Identifier: GPL-3.0-or-later
plugins {
    kotlin("jvm") version "2.0.21"
}

group = "io.github.marybezuhla"
version = "0.1.0"

repositories {
    mavenCentral()
}

dependencies {
    // Ed25519 for Android 12, which has no built-in support (MIT-style licence, GPL-compatible).
    implementation("org.bouncycastle:bcprov-jdk18on:1.78.1")
    testImplementation("junit:junit:4.13.2")
    // The JVM stand-ins for what Android gives the app: SQLite (Apache 2.0) and zstd (BSD).
    testImplementation("org.xerial:sqlite-jdbc:3.46.1.0")
    testImplementation("com.github.luben:zstd-jni:1.5.5-11")
}

kotlin {
    jvmToolchain(17)
    compilerOptions {
        allWarningsAsErrors = true
    }
}

tasks.test {
    useJUnit()
    // The tests read ../testdata, shared with the Python library.
    workingDir = projectDir
}
