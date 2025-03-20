import nuke
import os


def fix():
    writeNode = nuke.thisNode()
    group = ''.join(nuke.thisNode().fullName().split('.')[:-1])
    groupNode = nuke.toNode(group)
    if groupNode.knob("_promoted_0").value() != None:
        writeNode.knob("compression").setValue(groupNode.knob("_promoted_0").value())