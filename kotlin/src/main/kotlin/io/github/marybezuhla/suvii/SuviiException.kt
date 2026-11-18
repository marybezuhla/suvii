// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

/**
 * Any problem with a scroll. [code] is stable and machine-readable, so an app can show its own
 * translated message instead of raw text; [detail] is for logs and tests only.
 */
class SuviiException(val code: String, val detail: String = "") :
    Exception(if (detail.isEmpty()) code else "$code: $detail")
