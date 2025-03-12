# -*- coding: utf-8 -*-
"""
QGIS Server Plugin to provide project information via JSON endpoint
"""

import os
import json
from qgis.server import (
    QgsService,
    QgsServerRequest,
    QgsServerResponse
)
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsApplication
)
from qgis.PyQt.QtCore import QFileInfo


class ProjectInfoService(QgsService):
    """QGIS Server service that provides info about all published projects"""

    def __init__(self, serverIface):
        super().__init__()
        self.serverIface = serverIface
        self.logger = serverIface.serverLogger()
        
    def name(self):
        """Return the service name"""
        return "PROJECTINFO"
        
    def version(self):
        """Return the service version"""
        return "1.0.0"
        
    def allowMethod(self, method):
        """Check if the HTTP method is allowed"""
        return method in [QgsServerRequest.GetMethod, QgsServerRequest.PostMethod]
        
    def executeRequest(self, request, response, project):
        """Process the request and generate the appropriate response"""
        params = request.parameters()
        
        # Log the request for debugging
        self.logger.logMessage(f"ProjectInfo request parameters: {params}")
        
        # Determine which action to take
        req_param = params.get('REQUEST', '').upper()
        
        # Handle requests that don't need a project file
        if req_param == 'GETPROJECTS':
            self.get_projects(request, response)
            return True
            
        elif req_param == 'GETPROJECTDETAILS':
            project_path = params.get('PROJECT', '')
            if project_path:
                self.get_project_details(request, response, project_path)
                return True
            else:
                self.send_error_response(response, "Missing PROJECT parameter", 400)
                return True
                
        # If we get here with no valid request, default to project list
        self.get_projects(request, response)
        return True

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
            self.send_error_response(response, "Project not found", 404)
            return
        
        # Load project and extract detailed information
        project_info = self.get_detailed_project_info(full_path)
        
        if project_info:
            self.send_json_response(response, project_info)
        else:
            self.send_error_response(response, "Failed to read project information", 500)

    def get_basic_project_info(self, project_path):
        """Extract basic information from a project without fully loading it"""
        try:
            # For basic info, we'll just use the file properties
            file_info = QFileInfo(project_path)
            return {
                'title': file_info.baseName(),
                'path': project_path,
                'size': os.path.getsize(project_path),
                'modified': os.path.getmtime(project_path)
            }
        except Exception as e:
            self.logger.logMessage(f"Error reading project {project_path}: {str(e)}", 2)
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
            self.logger.logMessage(f"Error reading detailed project info {project_path}: {str(e)}", 2)
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
        projects_dir = self.serverIface.serverSettings().value('qgis_server_projects_dir')
        
        if not projects_dir:
            # Try alternative settings key
            projects_dir = self.serverIface.serverSettings().value('QGIS_SERVER_PROJECTS_DIR')
            
        if not projects_dir:
            # Try environment variable
            projects_dir = os.environ.get('QGIS_SERVER_PROJECTS_DIR')
            
        if not projects_dir:
            # Check landing page directories (useful for Camptocamp image)
            landing_page_dirs = os.environ.get('QGIS_SERVER_LANDING_PAGE_PROJECTS_DIRECTORIES', '')
            if landing_page_dirs:
                # Use the first directory from the list
                projects_dir = landing_page_dirs.split('||')[0]
                
        if not projects_dir:
            # For Camptocamp image, the default is almost always /project
            if os.path.exists('/project'):
                projects_dir = '/project'
            
        if not projects_dir or not os.path.exists(projects_dir):
            # Fallback to default location
            projects_dir = os.path.join(QgsApplication.qgisSettingsDirPath(), "server")
            
        # Create the directory if it doesn't exist
        if not os.path.exists(projects_dir):
            os.makedirs(projects_dir)
            
        self.logger.logMessage(f"ProjectInfo plugin: Using projects directory: {projects_dir}")
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
    
    def __init__(self, serverIface):
        self.serverIface = serverIface
        self.service = ProjectInfoService(serverIface)
        
        # Register the service with QGIS Server
        self.serverIface.registerService(self.service)
        
        # Log plugin startup
        serverIface.serverLogger().logMessage('ProjectInfo plugin loaded and service registered')