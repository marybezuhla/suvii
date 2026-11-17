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
