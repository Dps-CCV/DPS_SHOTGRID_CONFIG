from sgtk.platform import Application


class ContextSetup(Application):
    """
    Reads the latest publishes of the shot of the current context and builds
    the Nuke scene: project settings (frame range, fps, format) and one node,
    inside its own backdrop, for each publish.
    """

    def init_app(self):
        payload = self.import_module("app")
        callback = lambda: payload.builder.run(self)
        self.engine.register_command(
            "Setup Shot Scene",
            callback,
            {"type": "context_menu", "short_name": "setup_shot_scene"},
        )
