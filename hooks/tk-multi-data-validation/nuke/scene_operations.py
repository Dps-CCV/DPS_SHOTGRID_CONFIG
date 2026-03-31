# Copyright (c) 2024 Autodesk Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the ShotGrid Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the ShotGrid Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Autodesk Inc.

import sgtk
import nuke

HookBaseClass = sgtk.get_hook_baseclass()


class NukeSceneOperationsHook(HookBaseClass):
    """Hook class that sets up Nuke events to update the Data Validation App."""

    def __init__(self, *args, **kwargs):
        super(NukeSceneOperationsHook, self).__init__(*args, **kwargs)
        self.__reset_callback = None
        self.__change_callback = None
        self.__callbacks_registered = False

    def register_scene_events(self, reset_callback, change_callback):
        """
        Register events for when the scene has changed.

        :param reset_callback: Callback function to reset the Data Validation App.
        :type reset_callback: callable
        :param change_callback: Callback function to handle the changes to the scene.
        :type change_callback: callable
        """

        if self.__callbacks_registered:
            return  # Scene events already registered

        # Store callbacks
        self.__reset_callback = reset_callback
        self.__change_callback = change_callback

        # Register Nuke scene events
        nuke.addOnScriptLoad(self._on_script_loaded)
        nuke.addOnScriptSave(self._on_script_saved)
        nuke.addOnScriptClose(self._on_script_closed)

        # Register Nuke node events
        nuke.addOnCreate(self._on_node_created, nodeClass='*')
        nuke.addOnDestroy(self._on_node_removed, nodeClass='*')

        self.__callbacks_registered = True
        self.logger.info("Callbacks registered")

    def unregister_scene_events(self):
        """Unregister the scene events."""
        self.__reset_callback = None
        self.__change_callback = None
        self.__callbacks_registered = False

    # Scene event callbacks
    # -------------------------------------------------------------------------

    def _on_script_loaded(self):
        """Callback when a script is loaded."""
        if self.__reset_callback:
            self._defer_callback(self.__reset_callback)

    def _on_script_saved(self):
        """Callback when a script is saved."""
        pass

    def _on_script_closed(self):
        """Callback when a script is closed."""
        if self.__reset_callback:
            self._defer_callback(self.__reset_callback)

    # Node event callbacks
    # -------------------------------------------------------------------------

    def _on_node_created(self):
        """Callback when a node is created."""
        if self.__change_callback:
            self._defer_callback(lambda: self.__change_callback(text="Node added"))

    def _on_node_removed(self):
        """Callback when a node is removed."""
        if self.__change_callback:
            self._defer_callback(lambda: self.__change_callback(text="Node removed"))

    # Utility methods
    # -------------------------------------------------------------------------

    def _defer_callback(self, callback):
        """
        Defer callback execution to avoid UI timing issues.

        CRITICAL: This prevents the "PythonObject is not attached to a node" error
        by ensuring callbacks execute after the current operation completes and
        the UI has time to update.

        :param callback: The callback function to execute
        """
        try:
            from sgtk.platform.qt import QtCore

            # Execute callback after current event loop iteration completes
            # Using 0ms delay ensures it runs after the delete operation finishes
            QtCore.QTimer.singleShot(0, callback)

        except Exception as e:
            self.logger.warning(
                "Could not defer callback execution (Qt not available): %s" % str(e)
            )
            # Fallback: execute immediately (may cause errors)
            try:
                callback()
            except Exception as e2:
                self.logger.error("Error executing callback: %s" % str(e2))