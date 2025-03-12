"""
QGIS Server Plugin to provide project information via JSON endpoint
Name: ProjectInfo
qgisMinimumVersion: 3.0
description: Exposes information about all published QGIS projects as JSON
version: 0.1
server: True
"""

import os
import json
from qgis.server import (
    QgsServerInterface,
    QgsServerRequest,
    QgsServerResponse,
    QgsServiceModule
)
from qgis.core import (
    QgsProject,
    QgsProjectSerializer,
    QgsCoordinateReferenceSystem,
    QgsApplication
)
from qgis.PyQt.QtCore import QFileInfo, QDir

class ProjectInfoModule(QgsServiceModule):
    """QGIS Server module that provides info about all published projects"""

    def __init__(self, server_iface):
        super().__init__()
        self.server_iface = server_iface
        # Register the service with QGIS Server
        self.server_iface.registerService(self)

    def createServiceCapabilities(self, doc):
        """Define service capabilities in GetCapabilities response"""
        # Implement if needed for WMS/WFS GetCapabilities integration
        pass

    def executeRequest(self, request, response, project):
        """Handle the incoming request and generate response"""
        # Check if this is a request for our service
        if request.parameters().get('SERVICE', '').upper() == 'PROJECTINFO':
            # Get the specific action
            action = request.parameters().get('REQUEST', '').upper()
            
            if action == 'GETPROJECTS':
                self.get_projects(request, response)
                return True
            elif action == 'GETPROJECTDETAILS':
                project_path = request.parameters().get('PROJECT', '')
                if project_path:
                    self.get_project_details(request, response, project_path)
                    return True
            else:
                # Default action
                self.get_projects(request, response)
                return True
                
        # Not our request
        return False

    def get_projects(self, request, response):
        """Return list of all available projects"""
        projects_dir = self.get_projects_directory()
        
        # Scan for .qgs and .qgz files
        project_files = []
        for root, dirs, files in os.walk(projects_dir):
            for file in files:
                if file.endswith('.qgs') or file.endswith('.qgz'):
                    rel_path = os.path.relpath(os.path.join(root, file), projects_dir)
                    project_files.append(rel_path)
        
        # Basic info for each project
        projects_info = []
        for project_file in project_files:
            full_path = os.path.join(projects_dir, project_file)
            info = self.get_basic_project_info(full_path)
            if info:
                info['path'] = project_file
                projects_info.append(info)
        
        # Format response
        self.send_json_response(response, {
            'projects': projects_info,
            'count': len(projects_info),
            'projectsDirectory': projects_dir
        })

    def get_project_details(self, request, response, project_path):
        """Return detailed information about a specific project"""
        projects_dir = self.get_projects_directory()
        full_path = os.path.join(projects_dir, project_path)
        
        if not os.path.exists(full_path):
            self.send_error_response(response, "Project not found")
            return
        
        # Load project and extract detailed information
        project_info = self.get_detailed_project_info(full_path)
        
        if project_info:
            self.send_json_response(response, project_info)
        else:
            self.send_error_response(response, "Failed to read project information")

    def get_basic_project_info(self, project_path):
        """Extract basic information from a project without fully loading it"""
        # We use a lightweight approach for the project list
        try:
            # Use QgsProjectSerializer to extract basic metadata without full project load
            with open(project_path, 'rb') as f:
                # Just read the file header to get basic info
                project_data = f.read(8192)  # Read first 8KB which should contain metadata
                
            file_info = QFileInfo(project_path)
            return {
                'title': file_info.baseName(),  # Use filename as a fallback title
                'path': project_path,
                'size': os.path.getsize(project_path),
                'modified': os.path.getmtime(project_path)
            }
        except Exception as e:
            self.server_iface.logMessage(f"Error reading project {project_path}: {str(e)}")
            return None
            
    def get_detailed_project_info(self, project_path):
        """Extract detailed information from a project by loading it"""
        try:
            # Create a temporary project instance
            temp_project = QgsProject()
            if not temp_project.read(project_path):
                return None
                
            # Extract detailed project information
            info = {
                'title': temp_project.title() or QFileInfo(project_path).baseName(),
                'fileName': QFileInfo(project_path).fileName(),
                'path': project_path,
                'modified': os.path.getmtime(project_path),
                'projection': {
                    'authid': temp_project.crs().authid(),
                    'description': temp_project.crs().description(),
                    'proj4': temp_project.crs().toProj4()
                },
                'layers': []
            }
            
            # Add layer information
            for layer_id, layer in temp_project.mapLayers().items():
                layer_info = {
                    'id': layer_id,
                    'name': layer.name(),
                    'type': layer.type(),
                    'source': layer.source(),
                    'crs': {
                        'authid': layer.crs().authid(),
                        'description': layer.crs().description()
                    }
                }
                info['layers'].append(layer_info)
                
            # Add layer tree information
            info['layerTree'] = self.extract_layer_tree(temp_project.layerTreeRoot())
            
            # Add composer/layout information
            info['layouts'] = []
            for layout in temp_project.layoutManager().layouts():
                layout_info = {
                    'name': layout.name(),
                    'width': layout.paperWidth(),
                    'height': layout.paperHeight(),
                    'itemCount': len(layout.items())
                }
                info['layouts'].append(layout_info)
                
            return info
            
        except Exception as e:
            self.server_iface.logMessage(f"Error reading detailed project info {project_path}: {str(e)}")
            return None

    def extract_layer_tree(self, layer_tree_node):
        """Extract layer tree structure"""
        result = {
            'type': 'group' if layer_tree_node.nodeType() == 0 else 'layer',
            'name': layer_tree_node.name(),
            'visible': layer_tree_node.isVisible(),
            'children': []
        }
        
        # Add children if this is a group
        if layer_tree_node.nodeType() == 0:  # Group
            for child in layer_tree_node.children():
                result['children'].append(self.extract_layer_tree(child))
                
        return result

    def get_projects_directory(self):
        """Get the directory containing QGIS projects"""
        # Try to get from server configuration
        projects_dir = self.server_iface.serverSettings().value('projectsDirectories')
        
        if not projects_dir:
            # Fallback to default location
            projects_dir = QgsApplication.qgisSettingsDirPath() + "server"
            
        return projects_dir

    def send_json_response(self, response, data):
        """Send a JSON response"""
        response.setStatusCode(200)
        response.setHeader("Content-Type", "application/json")
        response.write(json.dumps(data, indent=2))

    def send_error_response(self, response, message, status=404):
        """Send an error response"""
        response.setStatusCode(status)
        response.setHeader("Content-Type", "application/json")
        response.write(json.dumps({
            'error': True,
            'message': message
        }, indent=2))


class ProjectInfoServer:
    """QGIS Server Plugin implementation"""
    
    def __init__(self, server_iface):
        self.server_iface = server_iface
        self.service_module = ProjectInfoModule(server_iface)
        
        # Register the service
        server_iface.serviceRegistry().registerService(self.service_module)
        
        # Log plugin startup
        server_iface.logMessage('ProjectInfo plugin loaded')


def serverClassFactory(server_iface):
    """Load the plugin when QGIS Server starts"""
    return ProjectInfoServer(server_iface)