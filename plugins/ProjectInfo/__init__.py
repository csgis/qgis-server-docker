# -*- coding: utf-8 -*-
"""
 This script initializes the plugin, making it known to QGIS.
"""

def serverClassFactory(serverIface):
    """Load ProjectInfoServer class from ProjectInfo.ProjectInfoServer.
    
    This function is called when the QGIS Server loads our plugin.
    
    :param serverIface: A QGIS Server Interface instance.
    :type serverIface: QgsServerInterface
    """
    from .ProjectInfoServer import ProjectInfoServer
    return ProjectInfoServer(serverIface)