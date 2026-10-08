package com.toad.companion.ui

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import kotlin.math.PI
import kotlin.math.sin

/** Same six expression states and layout contract as the baseline companion. */
enum class Expression { Dozing, Listening, Thinking, Talking, Muted, Peeking }

/** Native vector toad: no bitmap/model download is needed for the default character. */
@Composable
fun DrawnToad(
    expression: Expression,
    width: Dp,
    modifier: Modifier = Modifier,
    halo: Boolean = true,
    rings: Boolean = expression == Expression.Listening,
    animate: Boolean = true,
    level: Float = 0f,
    lookAt: Float? = null,
    voiceDriven: Boolean = false,
) {
    val transition = rememberInfiniteTransition(label = "toad")
    val blink by transition.animateFloat(
        1f, 1f,
        infiniteRepeatable(keyframes {
            durationMillis = 6400
            1f at 2600; .08f at 2680; 1f at 2780
            1f at 5600; .08f at 5680; 1f at 5760; .08f at 5880; 1f at 5960
        }), label = "blink",
    )
    val breathe by transition.animateFloat(1f, 1.04f,
        infiniteRepeatable(tween(3000, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "breathe")
    val bob by transition.animateFloat(0f, 1f,
        infiniteRepeatable(tween(1200, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "bob")
    val talk by transition.animateFloat(.2f, 1f,
        infiniteRepeatable(tween(200), RepeatMode.Reverse), label = "talk")
    val ring by transition.animateFloat(0f, 1f,
        infiniteRepeatable(tween(2000, easing = LinearEasing)), label = "ring")
    val gaze by transition.animateFloat(-1f, 1f,
        infiniteRepeatable(tween(3800), RepeatMode.Reverse), label = "gaze")
    val voice by animateFloatAsState(level.coerceIn(0f, 1f), tween(110), label = "voice")
    val follow by animateFloatAsState(lookAt?.coerceIn(-1f, 1f) ?: 0f,
        tween(600, easing = FastOutSlowInEasing), label = "follow")
    val ratio = when (expression) {
        Expression.Listening -> 205f / 240f
        Expression.Talking -> 145f / 170f
        Expression.Dozing -> 170f / 200f
        else -> 54f / 64f
    }
    val sleepy = expression == Expression.Dozing || expression == Expression.Muted
    val eyeOpen = if (sleepy) .12f else if (animate) blink else 1f
    val look = when {
        sleepy || !animate -> 0f
        lookAt != null -> follow * 7f
        expression == Expression.Thinking -> 5f
        expression == Expression.Peeking -> 6f
        else -> gaze * 2f
    }
    val mouth = when {
        expression != Expression.Talking -> 0f
        !animate -> .5f
        voiceDriven -> voice
        voice > .03f -> voice
        else -> talk
    }
    val moss = Color(0xFF87A866)
    val shadow = Color(0xFF5B7547)
    val cream = Color(0xFFDDE8AF)
    val ink = Color(0xFF202A36)
    val teal = Color(0xFF63C6BB)
    Canvas(modifier.size(width, width * ratio).graphicsLayer {
        val breathScale = if (animate && expression == Expression.Dozing) breathe else 1f
        scaleX = breathScale
        scaleY = breathScale
        translationY = if (animate && expression == Expression.Listening) -size.width * .02f * bob else 0f
        alpha = if (expression == Expression.Muted) .72f else 1f
    }.semantics { contentDescription = "Toad, ${expression.name.lowercase()}" }) {
        val sx = size.width / 240f
        val sy = size.height / 205f
        fun point(x: Float, y: Float) = Offset(x * sx, y * sy)
        fun oval(color: Color, x: Float, y: Float, w: Float, h: Float) =
            drawOval(color, point(x, y), Size(w * sx, h * sy))
        if (halo && expression != Expression.Muted) {
            val radius = size.width * (.62f + .15f * voice)
            drawCircle(Brush.radialGradient(listOf(teal.copy(alpha = .16f + .18f * voice),
                Color.Transparent), center = center, radius = radius), radius, center)
        }
        if (rings && animate) {
            listOf(ring, (ring + .5f) % 1f).forEach { phase ->
                val radius = size.width * (.48f + .25f * phase + .08f * voice)
                drawCircle(teal.copy(alpha = .4f * (1f - phase)), radius, center,
                    style = Stroke(1.5f * sx))
            }
        }
        // Rounded body, raised eye mounds and broad feet: a toad silhouette.
        oval(shadow, 15f, 166f, 65f, 35f)
        oval(shadow, 160f, 166f, 65f, 35f)
        val body = Path().apply {
            moveTo(34f * sx, 89f * sy)
            cubicTo(19f * sx, 22f * sy, 92f * sx, 4f * sy, 106f * sx, 58f * sy)
            quadraticBezierTo(120f * sx, 51f * sy, 134f * sx, 58f * sy)
            cubicTo(148f * sx, 4f * sy, 221f * sx, 22f * sy, 206f * sx, 89f * sy)
            cubicTo(255f * sx, 127f * sy, 222f * sx, 189f * sy, 176f * sx, 195f * sy)
            quadraticBezierTo(120f * sx, 207f * sy, 64f * sx, 195f * sy)
            cubicTo(18f * sx, 189f * sy, -15f * sx, 127f * sy, 34f * sx, 89f * sy)
            close()
        }
        drawPath(body, Brush.verticalGradient(listOf(moss, shadow)))
        oval(cream.copy(alpha = .7f), 63f, 125f, 114f, 62f)
        oval(cream, 39f, 35f, 65f, 70f)
        oval(cream, 136f, 35f, 65f, 70f)
        listOf(72f, 168f).forEach { x ->
            val pupilHeight = 30f * eyeOpen
            val up = if (expression == Expression.Thinking) -6f else 0f
            oval(ink, x - 12f + look, 71f - pupilHeight / 2f + up, 24f, pupilHeight)
            if (!sleepy && eyeOpen > .6f) {
                drawCircle(Color.White, 3f * sx, point(x + look + 4f, 64f + up))
            }
        }
        // Wide smile becomes a voice-driven mouth.
        val smile = Path().apply {
            moveTo(75f * sx, 113f * sy)
            quadraticBezierTo(120f * sx, (134f + mouth * 14f) * sy, 165f * sx, 113f * sy)
        }
        drawPath(smile, ink, style = Stroke(3f * sx))
        if (mouth > .03f) oval(ink, 96f, 117f, 48f, 21f * mouth)
        listOf(Offset(33f, 122f), Offset(43f, 143f), Offset(28f, 151f),
            Offset(207f, 122f), Offset(197f, 143f), Offset(212f, 151f)).forEach { spot ->
            drawCircle(shadow.copy(alpha = .7f), 4f * sx, point(spot.x, spot.y))
        }
        if (expression == Expression.Thinking) {
            repeat(3) { i ->
                val wave = if (animate) (sin((ring * 2f * PI + i).toFloat()) + 1f) / 2f else .5f
                drawCircle(teal.copy(alpha = .3f + .7f * wave), 2f * sx,
                    point(183f + i * 10f, 17f - 4f * wave))
            }
        }
    }
}
