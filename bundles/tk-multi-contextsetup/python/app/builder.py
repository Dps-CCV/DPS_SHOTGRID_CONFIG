"""
Builds the Nuke scene of the shot of the current context.

1. Script settings from FPT: frame range (cut in/out of the Shot) with the range
   locked, fps and full size format (from the Project).
2. One node per latest publish of the Shot (Read, ReadGeo2, Camera2, AudioRead),
   each one inside a backdrop with the info of the publish.

Running it again does not duplicate nodes: publishes whose file is already used by
a node of the script are skipped.
"""
import colorsys
import glob
import hashlib
import os
import re

import nuke
import sgtk

BUILD = "setup-shot-scene v1 (2026-11-23 17:30)"

IMAGE_EXTS = (
    ".png", ".jpg", ".jpeg", ".exr", ".cin", ".dpx", ".tiff", ".tif",
    ".mov", ".mp4", ".psd", ".tga", ".ari", ".gif", ".iff",
)
GEO_EXTS = (".abc", ".fbx", ".obj")
AUDIO_EXTS = (".wav", ".mp3", ".aif", ".aiff")

# layout (nuke DAG units)
BD_W, BD_H = 380, 260
COL_GAP, ROW_GAP = 60, 60
NODE_DX, NODE_DY = 150, 110


# ----------------------------------------------------------------------------
# pure helpers (no nuke needed)
# ----------------------------------------------------------------------------
def parse_resolution(text):
    """'1920x1080', '1920 x 1080 (HD)', '2048X858' -> (1920, 1080) or None."""
    if not text:
        return None
    m = re.search(r"(\d{3,5})\s*[xX×]\s*(\d{3,5})", str(text))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def latest_publishes(publishes):
    """Latest version of each (published file type, name)."""
    best = {}
    for pub in publishes:
        ftype = (pub.get("published_file_type") or {}).get("id")
        key = (ftype, pub.get("name") or pub.get("code"))
        cur = best.get(key)
        if cur is None or (pub.get("version_number") or 0) > (cur.get("version_number") or 0):
            best[key] = pub
    return list(best.values())


def classify(pub, path):
    """'read' | 'camera' | 'geo' | 'audio' | None."""
    ext = os.path.splitext(path)[1].lower()
    tname = ((pub.get("published_file_type") or {}).get("name") or "").lower()
    name = (pub.get("name") or "").lower()
    if ext in GEO_EXTS:
        if ext != ".obj" and ("camera" in tname or "camera" in name or re.search(r"(^|[_\W])cam([_\W]|$)", name)):
            return "camera"
        return "geo"
    if ext in IMAGE_EXTS:
        return "read"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def colorspace_for(path):
    """Same rules as the 'Create Read Node' action of the loader."""
    env = os.environ
    if "/SOURCE/" in path:
        return env.get("PROJECTCOLORSPACE")
    if "/VREF/" in path:
        return "Output - Rec.709"
    if "/PRECOMP/" in path or "/LAYERS/" in path:
        return env.get("PROJECTCOLORSPACE")
    if "/LGT/" in path:
        return "ACEScg"
    if "/DMP/" in path:
        return "Output - Rec.709"
    if "_CMP_" in path:
        return env.get("PROJECTCOLORSPACE")
    if "_ALPHA_" in path:
        return "Utility - Raw"
    if "_IMP_" in path:
        return "ACEScg"
    if "_IPL_" in path:
        return "Output - Rec.709"
    return None


def category_color(label):
    h = int(hashlib.md5(label.encode("utf-8")).hexdigest()[:6], 16) / float(0xFFFFFF)
    r, g, b = colorsys.hsv_to_rgb(h, 0.35, 0.45)
    return (int(r * 255) << 24) | (int(g * 255) << 16) | (int(b * 255) << 8) | 255


def norm_path(p):
    return (p or "").replace("\\", "/").lower()


# ----------------------------------------------------------------------------
# FPT
# ----------------------------------------------------------------------------
def _find_field(schema, configured, keyword):
    if configured and configured in schema:
        return configured
    for name in sorted(schema):
        if keyword in name.lower():
            return name
    return None


def _project_settings(app, project):
    sg = app.shotgun
    schema = sg.schema_field_read("Project")
    fmt_field = _find_field(schema, app.get_setting("format_field"), "resolucion")
    fps_field = _find_field(schema, app.get_setting("fps_field"), "fps")
    fields = [f for f in (fmt_field, fps_field) if f]
    data = sg.find_one("Project", [["id", "is", project["id"]]], fields) if fields else {}
    return (
        (data or {}).get(fmt_field) if fmt_field else None,
        (data or {}).get(fps_field) if fps_field else None,
        fmt_field,
        fps_field,
    )


# ----------------------------------------------------------------------------
# nuke
# ----------------------------------------------------------------------------
def _set_format(width, height):
    for f in nuke.formats():
        if f.width() == width and f.height() == height and abs(f.pixelAspect() - 1.0) < 1e-6:
            nuke.root()["format"].setValue(f.name())
            return f.name()
    name = "DPS_%dx%d" % (width, height)
    nuke.addFormat("%d %d 1 %s" % (width, height, name))
    nuke.root()["format"].setValue(name)
    return name


def _existing_files():
    files = set()
    for n in nuke.allNodes(recurseGroups=False):
        if n.Class() in ("Read", "ReadGeo2", "Camera2", "AudioRead") and n.knob("file"):
            files.add(norm_path(n["file"].value()))
    return files


def _sequence_range(app, path):
    """Same logic as the loader: first/last frame of the sequence found on disk."""
    frame_pattern = re.compile(r"([0-9#]+|[%]0\dd)$")
    root, ext = os.path.splitext(path)
    if not re.search(frame_pattern, root):
        return None
    files = glob.glob("%s%s" % (re.sub(frame_pattern, "*", root), ext))
    frames = []
    for f in files:
        m = re.search(frame_pattern, os.path.splitext(f)[0])
        if m and m.group(1).isdigit():
            frames.append(int(m.group(1)))
    return (min(frames), max(frames)) if frames else None


def _create_node(app, kind, path, pub):
    for n in nuke.selectedNodes():
        n.setSelected(False)
    if kind == "read":
        node = nuke.createNode("Read", "file {%s}" % path, inpanel=False)
        cs = colorspace_for(path)
        if cs:
            try:
                node["colorspace"].setValue(cs)
            except Exception as e:
                app.log_warning("Colorspace '%s' not set on %s: %s" % (cs, path, e))
        rng = _sequence_range(app, path)
        if rng:
            node["first"].setValue(rng[0])
            node["last"].setValue(rng[1])
    elif kind == "geo":
        node = nuke.createNode("ReadGeo2", "file {%s} tile_color %s" % (path, 4194238719), inpanel=False)
    elif kind == "camera":
        fps = nuke.root()["fps"].value()
        node = nuke.createNode(
            "Camera2",
            "read_from_file True file {%s} frame_rate %s tile_color %s" % (path, fps, 2822319615),
            inpanel=False,
        )
    else:  # audio
        node = nuke.createNode("AudioRead", "file {%s}" % path, inpanel=False)
        node["tile_color"].setValue(949013503)
    name = re.sub(r"\W", "_", pub.get("name") or pub.get("code") or kind)
    try:
        node.setName(name, uncollide=True)
    except Exception:
        pass
    return node


def _backdrop_label(pub, category):
    user = (pub.get("created_by") or {}).get("name") or ""
    created = pub.get("created_at")
    date = created.strftime("%Y-%m-%d %H:%M") if created else ""
    task = (pub.get("task") or {}).get("name") or ""
    lines = [
        "<b>%s</b>" % (pub.get("name") or pub.get("code")),
        "v%03d  |  %s" % (pub.get("version_number") or 0, category),
        "%s  %s" % (user, date),
    ]
    if task:
        lines.append("Task: %s" % task)
    if pub.get("description"):
        lines.append(pub["description"][:140])
    return "\n".join(lines)


def _origin():
    nodes = nuke.allNodes(recurseGroups=False)
    if not nodes:
        return 0, 0
    return max(n.xpos() + n.screenWidth() for n in nodes) + 300, min(n.ypos() for n in nodes)


# ----------------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------------
def run(app):
    ctx = app.context
    if not ctx.entity or ctx.entity.get("type") != "Shot":
        nuke.message("Setup Shot Scene: the current context has no Shot.")
        return
    sg = app.shotgun
    report = []

    cut_in_f, cut_out_f = app.get_setting("cut_in_field"), app.get_setting("cut_out_field")
    shot = sg.find_one("Shot", [["id", "is", ctx.entity["id"]]], ["code", "project", cut_in_f, cut_out_f])
    project = shot["project"]
    fmt_text, fps_value, fmt_field, fps_field = _project_settings(app, project)

    undo = nuke.Undo()
    undo.begin("Setup Shot Scene")
    try:
        # ---- script settings
        root = nuke.root()
        cut_in, cut_out = shot.get(cut_in_f), shot.get(cut_out_f)
        if cut_in is not None and cut_out is not None:
            root["first_frame"].setValue(int(cut_in))
            root["last_frame"].setValue(int(cut_out))
            root["lock_range"].setValue(True)
            report.append("Frame range: %s-%s (locked)" % (int(cut_in), int(cut_out)))
        else:
            report.append("WARNING: the Shot has no %s/%s." % (cut_in_f, cut_out_f))

        if fps_value:
            root["fps"].setValue(float(fps_value))
            report.append("FPS: %s" % fps_value)
        else:
            report.append("WARNING: no fps in the Project (field %s)." % (fps_field,))

        res = parse_resolution(fmt_text)
        if res:
            report.append("Format: %s (%s)" % ("%dx%d" % res, _set_format(*res)))
        else:
            report.append("WARNING: could not read the format of the Project (%s = %r)." % (fmt_field, fmt_text))

        # ---- publishes
        fields = [
            "id", "code", "name", "version_number", "path", "published_file_type",
            "created_by", "created_at", "description", "task",
        ]
        pubs = sg.find(
            "PublishedFile",
            [["entity", "is", {"type": "Shot", "id": shot["id"]}]],
            fields,
            order=[{"field_name": "version_number", "direction": "desc"}],
        )
        skip_types = set(t.strip() for t in (app.get_setting("skip_published_file_types") or "").split(",") if t.strip())
        pubs = [
            p for p in latest_publishes(pubs)
            if (p.get("published_file_type") or {}).get("name") not in skip_types
        ]

        existing = _existing_files()
        columns = {}
        origin_x, origin_y = _origin()
        created = skipped = 0
        for pub in sorted(
            pubs,
            key=lambda p: (
                (p.get("published_file_type") or {}).get("name") or "",
                p.get("name") or "",
            ),
        ):
            label = "%s v%03d" % (pub.get("name"), pub.get("version_number") or 0)
            try:
                path = sgtk.util.resolve_publish_path(app.sgtk, pub).replace(os.path.sep, "/")
            except Exception as e:
                report.append("SKIPPED %s: path could not be resolved (%s)" % (label, e))
                skipped += 1
                continue
            kind = classify(pub, path)
            if not kind:
                skipped += 1
                app.log_debug("Setup Shot Scene: %s is not supported (%s)" % (label, path))
                continue
            if norm_path(path) in existing:
                report.append("Already in the script: %s" % label)
                skipped += 1
                continue

            category = (pub.get("published_file_type") or {}).get("name") or "Other"
            col = columns.setdefault(category, {"index": len(columns), "rows": 0})
            x = origin_x + col["index"] * (BD_W + COL_GAP)
            y = origin_y + col["rows"] * (BD_H + ROW_GAP)
            col["rows"] += 1

            try:
                node = _create_node(app, kind, path, pub)
            except Exception as e:
                report.append("ERROR creating the node of %s: %s" % (label, e))
                skipped += 1
                col["rows"] -= 1
                continue
            node.setXYpos(x + NODE_DX, y + NODE_DY)
            bd = nuke.nodes.BackdropNode(
                xpos=x,
                ypos=y,
                bdwidth=BD_W,
                bdheight=BD_H,
                label=_backdrop_label(pub, category),
                note_font_size=20,
                tile_color=category_color(category),
            )
            bd.setName("BD_" + re.sub(r"\W", "_", pub.get("name") or "publish"), uncollide=True)
            existing.add(norm_path(path))
            created += 1

        report.append("Nodes created: %d, skipped: %d" % (created, skipped))
    finally:
        undo.end()

    app.log_info("[%s] %s" % (BUILD, " | ".join(report)))
    nuke.message("Setup Shot Scene\n\n" + "\n".join(report))
