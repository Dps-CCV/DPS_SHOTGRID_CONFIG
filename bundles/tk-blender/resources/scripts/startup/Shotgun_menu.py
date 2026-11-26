# ----------------------------------------------------------------------------
# Copyright (c) 2020, Diego Garcia Huerta.
#
# Your use of this software as distributed in this GitHub repository, is
# governed by the Apache License 2.0
#
# Your use of the Shotgun Pipeline Toolkit is governed by the applicable
# license agreement between you and Autodesk / Shotgun.
#
# The full license is in the file LICENSE, distributed with this software.
# ----------------------------------------------------------------------------


import os
import sys
import importlib.util
import time
import ast
import inspect

import bpy
from bpy.types import Header, Menu, Panel, Operator
from bpy.app.handlers import load_factory_startup_post, persistent

import site

DIR_PATH = os.path.dirname(os.path.abspath(__file__))

# folder(s) where PySide6/PySide2 have been installed (pip --target ...)
for _var in ("PYSIDE_PYTHONPATH", "PYSIDE6_PYTHONPATH", "PYSIDE2_PYTHONPATH"):
    ext_libs = os.environ.get(_var)
    if ext_libs and os.path.exists(ext_libs) and ext_libs not in sys.path:
        print("Added path: %s" % ext_libs)
        site.addsitedir(ext_libs)

bl_info = {
    "name": "Shotgun Bridge Plugin",
    "description": "Shotgun Toolkit Engine for Blender",
    "author": "Diego Garcia Huerta",
    "license": "GPL",
    "deps": "",
    "version": (1, 0, 0),
    "blender": (2, 82, 0),
    "location": "Shotgun",
    "warning": "",
    "wiki_url": "https://github.com/diegogarciahuerta/tk-blender/releases",
    "tracker_url": "https://github.com/diegogarciahuerta/tk-blender/issues",
    "link": "https://github.com/diegogarciahuerta/tk-blender",
    "support": "COMMUNITY",
    "category": "User Interface",
}


PYSIDE2_MISSING_MESSAGE = (
    "\n"
    + "-" * 80
    + "\nCould not import PySide6/PySide2 as a Python module. Shotgun menu will not be available."
    + "\n\nPlease check the engine documentation for more information:"
    + "\nhttps://github.com/diegogarciahuerta/tk-blender/edit/master/README.md\n"
    + "-" * 80
)

try:
    from PySide6 import QtWidgets, QtCore

    PYSIDE2_IMPORTED = True
except ModuleNotFoundError:
    try:
        from PySide2 import QtWidgets, QtCore

        PYSIDE2_IMPORTED = True
    except ModuleNotFoundError:
        PYSIDE2_IMPORTED = False


class ShotgunConsoleLog(bpy.types.Operator):
    """
    A simple operator to log issues to the console.
    """

    bl_idname = "shotgun.logger"
    bl_label = "Shotgun Logger"

    message: bpy.props.StringProperty(name="message", description="message", default="")

    level: bpy.props.StringProperty(name="level", description="level", default="INFO")

    def execute(self, context):
        self.report({self.level}, self.message)
        return {"FINISHED"}


# based on
# https://github.com/vincentgires/blender-scripts/blob/master/scripts/addons/qtutils/core.py
class QtWindowEventLoop(bpy.types.Operator):
    """
    Integration of qt event loop within Blender
    """

    bl_idname = "screen.qt_event_loop"
    bl_label = "Qt Event Loop"

    def __init__(self, *args, **kwargs):
        # Blender >= 4.x/5.x passes extra arguments to operator constructors
        self._app = None
        self._timer = None
        self._event_loop = None

    def processEvents(self):
        self._event_loop.processEvents()
        self._app.sendPostedEvents(None, 0)

    def modal(self, context, event):
        if event.type == "TIMER":
            # keep pumping Qt events for the whole session, so Toolkit dialogs
            # opened at any time stay responsive
            self.processEvents()
        return {"PASS_THROUGH"}

    def anyQtWindowsAreOpen(self):
        return any(w.isVisible() for w in QtWidgets.QApplication.topLevelWidgets())

    def execute(self, context):
        # create a QApplication if already does not exists
        self._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            sys.argv
        )
        self._event_loop = QtCore.QEventLoop()

        # run modal
        wm = context.window_manager
        # self._timer = wm.event_timer_add(1 / 120, window=context.window)
        self._timer = wm.event_timer_add(0.01, window=context.window)
        context.window_manager.modal_handler_add(self)

        return {"RUNNING_MODAL"}

    def cancel(self, context):
        """Remove event timer when stopping the operator."""
        wm = context.window_manager
        wm.event_timer_remove(self._timer)


class TOPBAR_MT_shotgun(Menu):
    """
    Creates the Shotgun top level menu
    """

    bl_label = "Shotgun"
    bl_idname = "TOPBAR_MT_shotgun"

    def draw(self, context):
        try:
            import sgtk
        except ImportError:
            self.layout.label(text="Toolkit not started (see console)")
            return

        engine = sgtk.platform.current_engine()
        if engine:
            engine.display_menu()
        else:
            self.layout.label(text="Toolkit engine not running (see console)")


def draw_shotgun_menu(self, context):
    """
    Draw function appended to the top bar menus (after Help). Robust across
    Blender versions: no source code patching.
    """
    self.layout.menu(TOPBAR_MT_shotgun.bl_idname)


def boostrap():
    # start the engine
    SGTK_MODULE_PATH = os.environ.get("SGTK_MODULE_PATH")
    if SGTK_MODULE_PATH and SGTK_MODULE_PATH not in sys.path:
        sys.path.insert(0, SGTK_MODULE_PATH)

    engine_startup_path = os.environ.get("SGTK_BLENDER_ENGINE_STARTUP")
    spec = importlib.util.spec_from_file_location(
        "sgtk_blender_engine_startup", engine_startup_path
    )
    engine_startup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine_startup)

    # Fire up Toolkit and the environment engine.
    engine_startup.start_toolkit()


_STARTED = {"done": False}


@persistent
def startup(dummy):
    # run only once per session (factory startup and load_post may both fire)
    if _STARTED["done"]:
        return
    _STARTED["done"] = True
    bpy.ops.screen.qt_event_loop()
    boostrap()


@persistent
def error_importing_pyside2(*args):
    bpy.ops.shotgun.logger(level="ERROR", message=PYSIDE2_MISSING_MESSAGE)


def register():
    bpy.utils.register_class(ShotgunConsoleLog)

    if not PYSIDE2_IMPORTED:
        # bpy.app.timers.register(error_importing_pyside2, first_interval=5)
        load_factory_startup_post.append(error_importing_pyside2)
        return

    bpy.utils.register_class(QtWindowEventLoop)
    bpy.utils.register_class(TOPBAR_MT_shotgun)
    bpy.types.TOPBAR_MT_editor_menus.append(draw_shotgun_menu)

    # factory startup does not fire when a file is opened from the command
    # line, so also start on the first load_post (guarded by _STARTED).
    load_factory_startup_post.append(startup)
    bpy.app.handlers.load_post.append(startup)


def unregister():
    bpy.utils.unregister_class(ShotgunConsoleLog)

    if not PYSIDE2_IMPORTED:
        return

    bpy.types.TOPBAR_MT_editor_menus.remove(draw_shotgun_menu)
    bpy.utils.unregister_class(TOPBAR_MT_shotgun)
