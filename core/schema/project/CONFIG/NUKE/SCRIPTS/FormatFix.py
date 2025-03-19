import nuke
import os


def fix():
    writeNode = nuke.thisNode()
    group = ''.join(nuke.thisNode().fullName().split('.')[:-1])
    groupNode = nuke.toNode(group)
    if groupNode.knob('tk_profile_list').value() in ['PRECOMP', 'Render 16bits']:
        writeNode.knob("file_type").setValue(os.environ["FormExt"])
        writeNode.knob("compression").setValue(os.environ["CompressionExt"])