# IGI + SAM — Flaws & Integration Vision

**Saved:** 2026-11-01 ~02:45 IST (2026-10-31 21:15 UTC)
**Context:** Live IGI session in Antigravity IDE (`meta hackathon` workspace) — user asked about IGI flaws, then about SAM + Enheduanna incorporation problems.

---

## 1. User: "what are the flaws of igi"

### Assistant Response — Flaws of IGI

Based on live screen + actual IGI code in `enheduanna/igi/`:

You're seeing them right now in Antigravity: the right panel says `hud gets froze for few second` + `crash with python not responding`, and `doesnt like segment the right things... doesnt have the brain`.

### 1. Live Session freezes because network runs on the UI thread

`sam/cloud_sam3.py` uses a sync `httpx.Client(timeout=30.0)` with `stream(POST ... timeout=25.0)`.

`hud/chat_window.py` calls that directly from the button slot. So when you click `Live Sess`:
- Qt event loop blocks waiting for Meta API
- HUD can't repaint for a few seconds = freeze
- If you click again, you queue 2-3 blocking 25s requests on the same thread = `Python not responding` crash

There is no `QThread`, no worker, no cancel. That's flaw #1.

### 2. "SAM 2 Local" isn't SAM at all

`sam/local_sam2.py` -> `LocalSAM2Engine`:

```python
self._onnx_session = None  # never loaded
```

`segment_gesture()` just does `compute_bounding_box(stroke_points)` — a rectangle around your mouse stroke.

`refine_box()` just does `x1-padding, y1-padding...` — no gradient, no edge snap, despite the docstring saying "contrast / gradient analysis".

So circling never snaps to buttons. It's geometric math, not a model.

### 3. "SAM 3" is fragile + blind

- Downscales everything to max 1280px + JPEG 85 before sending — small UI text / icons get destroyed
- Parses streaming `data:` lines with string concat + regex on `accum_text` to find boxes. If Meta changes token format, you get zero boxes or wrong boxes
- Needs `META_API_KEY` — offline = no segmentation at all
- Fixed `threshold=0.5`, no per-concept calibration — that's why `graph mode it detected the graphs easily then it shouldnt` — it over-fires on anything graph-like

### 4. No brain to restrict *where*

You said it perfectly: `when i get the answer it should restrict where the`

Right now:
- `route_gesture()` and `route_concept()` are separate in `sam/router.py`
- `extract_concept_from_prompt()` in `chat_window.py` is a giant prefix-strip list — `where can i find the`, `highlight the`, `mark the`... — brittle. If you phrase differently, concept = wrong.
- The new `ground_target(region_hint, exclude_rect)` that does `SAM 3.1 on sub-region + SAM 2 refine` exists in `router.py`, but the Live path doesn't use it yet. So it searches full 2560x1440 every time.

No LLM -> region -> SAM pipeline in the live click path.

### 5. SAM 2 + SAM 3.1 aren't fused

What you asked for — `integrate sam 2 + sam 3.1 together` — is exactly what's missing. Current flow is:
`SAM 3 rough box -> SAM 2 refine (which is just +4px padding)`

No joint scoring, no verification that SAM 2 edges agree with SAM 3 mask, no fallback if they disagree.

### 6. Small stability debt you can see in your terminal

Bottom terminal:
`SystemTrayIcon::setVisible: No Icon set` — `main.py` creates `QSystemTrayIcon()` with no `QIcon`, so tray never shows.

Hotkey confusion: `config.py` says `<ctrl>+<shift>+q`, tooltip says `Ctrl+Shift+Q`, startup banner you saw earlier said `ctrl+shift+space`. Three different shortcuts documented.

`segment_credit.py` in the repo isn't credit logic — it's a one-off `$131.29 free credits` halo test script. Ad-hoc test files living in prod code.

**In one line:** IGI freezes because it does 25s network on the UI thread, and mis-segments because Local SAM 2 is a stub bbox and Cloud SAM 3 has no region brain + no true fusion.

Fix order:
1. Move `route_concept / ground_target` to `QThread` + cancel button — kills freeze/crash
2. Make Live use `ground_target()` with LLM region_hint (`top/sidebar/right/bottom/center`) + `exclude_rect` for your own HUD
3. Replace `refine_box` stub with real MobileSAM-ONNX or at least edge-based snap

---

## 2. User: "so i am getting problems like using sam with enheduanna since just sending prompt and a image or am i just sending text not a prompt even idk how to incoprate the sam with igi, but you pretty much know my vison what i am trying to do with sam and igi"

### Assistant Response — SAM + IGI Incorporation

You're confused for the right reason — you **are** sending image + text, but you're not sending a **SAM prompt**.

That's the core disconnect in IGI right now. Your vision:

> Circle anything -> IGI understands what it is -> segments the *right* thing -> projects a halo + explanation card live on screen -> restricts search to where the answer should be.

Right now SAM and Enheduanna are running as two strangers. They need to be brain + eyes.

### 1. What SAM actually wants vs what you're sending

**SAM 2 (local) wants visual prompts, not text.**
Points, boxes, masks. `local_sam2.py` right now never loads a model — `segment_gesture()` just draws a rectangle around your mouse stroke. So circling does no snapping at all.

**SAM 3.1 (cloud) wants image + *instructed* concept, not a bare word.**
In `sam/cloud_sam3.py` you send this:

```python
{"type": "input_text", "text": concept},  # concept = "advisories" or "update"
{"type": "input_image", "image_url": f"data:image/jpeg;base64,{img_b64}"}
```

That's text, not a prompt. You never tell it:
- what task to do (locate + return boxes)
- what coordinate format to return in
- to return JSON only, no chat

So SAM 3.1 returns free-form chat text, and then you try to regex boxes out of `accum_text`. That's why it sometimes works on big graphs and fails on small buttons — it's guessing, not grounding.

Also: `threshold=0.5` is defined in the function but never sent in the payload, and you downscale 2560x1440 to 1280px + JPEG 85 before sending. Small UI text is destroyed before SAM ever sees it.

### 2. What you're doing now

Trace your live path:

1. `overlay/canvas.py` freezes screen, gets stroke
2. `hud/chat_window.py` -> `extract_concept_from_prompt()` strips prefixes like `where can i find the` with a hard-coded list -> `concept = "advisories"`
3. `sam/router.py` -> `route_concept(full_screenshot, "advisories")` — full screen, no region
4. `bridge/core_client.py` -> `stream_chat_turn(prompt, image_crop)` to `127.0.0.1:4100` for explanation — separately, with no bbox knowledge

SAM doesn't know what Enheduanna thinks, Enheduanna doesn't know where SAM looked. No brain step in between.

### 3. How it *should* work for your vision

SAM is not the chatbot. Enheduanna core (Spark + Wonder) is the brain. SAM is the grounder. Projector is the hand.

Correct chain for IGI:

**Ask mode — "where is X":**

```
1. Brain: Spark sees thumbnail + OCR + window title
   -> { concept: "Update pill button", region_hint: "top", label: "Update" }

2. Ground: router.ground_target(screenshot, concept, region_hint="top")
   -> crop top 25% -> SAM 3.1 -> candidates in crop coords
   -> translate to full-screen coords -> exclude your own HUD rect
   -> SAM 2 refine: use SAM 3 box center as point prompt + box to snap tight

3. Project: projector.add_guidance_highlight(bbox, label, description)

4. Explain: Wonder synthesizes answer WITH bbox context
```

**Circle mode — user draws:**

```
stroke -> SAM 2 snap (real point/box prompt, not bbox math)
-> crop -> Brain explains what it is -> Projector confirms halo
```

**Live Session — auto walkthrough:**

```
Brain decomposes screen into blocks
-> SAM grounds each block -> projector.add_walkthrough_blocks()
```

You already built `ground_target(region_hint, exclude_rect)` in `router.py` that does 1-4 — but Live Sess doesn't use it yet. It still calls raw `route_concept()`.

### 4. What to fix to incorporate SAM properly

**A. Make a real SAM 3.1 prompt in `cloud_sam3.py`:**

Instead of sending bare `concept`, send:

```
Locate and segment UI element: "Update button in top-right title bar".
Return ONLY JSON: [{"bbox": [x1,y1,x2,y2], "confidence": 0-1}]
Coordinates in 0-1000 relative to this image. Return all matches, tight boxes.
```

Then parse JSON, not regex chat. And scale 0-1000 -> region crop -> full screen. Don't downscale small regions — send the region crop at full res.

**B. Always go Brain -> SAM, not SAM alone:**

In `chat_window.py`, before calling SAM:
1. Call core to get `concept + region_hint` from user query + screenshot thumbnail
2. Then call `ground_target(screenshot, concept, region_hint, exclude_rect=hud.geometry())`

That one change gives you what you asked for: *"when i get the answer it should restrict where the [highlight goes]"* and kills the full-screen false positives.

**C. Fuse SAM 2 + 3.1 for real:**

Right now `refine_box()` is just `+4px padding`. Real fusion:
- SAM 3.1 gives rough box
- Take its center as foreground point + box as prompt into MobileSAM / SAM 2 ONNX
- If SAM 2 mask IoU agrees, keep tight box. If they disagree, drop it as false positive.

That's the `integrate sam 2 + sam 3.1 together` you wrote on screen.

In one line: stop asking SAM to understand. Ask Enheduanna *what + where roughly*, ask SAM *exactly where in pixels*, then let Projector show it.

Do B first — route Live through `ground_target()` with an LLM region hint — and your freeze + wrong-segmentation complaints drop 80% even before you fix threading or load real SAM 2.
