# -*- coding: utf-8 -*-
"""
QGIS Server Plugin: ProjectInfo
Provides JSON endpoint for QGIS Server project information
as an extension to the WMS service
"""

import os
import json
from qgis.server import (
    QgsServerFilter,
    QgsServerRequest,
    QgsServerResponse
)
from qgis.core import (
    QgsProject,
    QgsMessageLog,
    Qgis
)

def log_message(message, level=Qgis.Info):
    """Helper to log messages"""
    QgsMessageLog.logMessage(message, 'ProjectInfo Plugin', level)

class ProjectInfoFilter(QgsServerFilter):
    """Filter that intercepts QGIS Server requests to provide project information"""
    
    def __init__(self, server_iface):
        super(ProjectInfoFilter, self).__init__(server_iface)
        self.server_iface = server_iface
        log_message("ProjectInfo filter initialized")
        
    def requestReady(self):
        """Called when request is ready but before it is processed"""
        handler = self.server_iface.requestHandler()
        params = handler.parameterMap()
        
        # Log all parameters for debugging
        log_message(f"Request parameters: {params}")
        
        # Check if this is a request for our plugin functionality
        # We're going to extend the WMS service with our custom REQUEST types
        service = params.get('SERVICE', '').upper()
        request_type = params.get('REQUEST', '').upper()
        
        # We'll hook into the WMS service
        if service != 'WMS':
            return
            
        # Check for our custom request types
        if request_type == 'GETPROJECTS':
            log_message("Handling GetProjects request")
            self.get_projects()
            return
        elif request_type == 'GETPROJECTDETAILS':
            log_message("Handling GetProjectDetails request")
            project_path = params.get('PROJECT', '')
            if project_path:
                self.get_project_details(project_path)
                return
            else:
                self.send_error_response("Missing PROJECT parameter", 400)
                return
        
        # If not our custom request type, let QGIS Server handle it normally
        return
        
    def get_projects(self):
        """Return list of all available projects"""
        try:
            projects_dir = "/io/data"  # Path for QGIS/QGIS Server image
            
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
                try:
                    # Extract project name (without extension)
                    project_name = os.path.splitext(os.path.basename(project_file))[0]
                    
                    # Check if the project is in a directory of the same name
                    parent_dir = os.path.dirname(project_file)
                    is_standard_structure = (os.path.basename(parent_dir) == project_name)
                    
                    info = {
                        'title': project_name,
                        'path': project_file,
                        'apiUrl': f"/api/projects/{project_file}" if not is_standard_structure else f"/api/projects/{project_name}",
                        'serviceUrl': f"/api/projectinfo/{project_name}" if is_standard_structure else None,
                        'modified': os.path.getmtime(full_path),
                        'size': os.path.getsize(full_path)
                    }
                    projects_info.append(info)
                except Exception as e:
                    log_message(f"Error getting info for {project_file}: {str(e)}", Qgis.Warning)
            
            # Return projects as JSON
            result = {
                'projects': projects_info,
                'count': len(projects_info),
                'projectsDirectory': projects_dir
            }
            
            self.send_json_response(result)
            
        except Exception as e:
            log_message(f"Error handling projects request: {str(e)}", Qgis.Critical)
            self.send_error_response(str(e), 500)

    def get_project_details(self, project_path):
        """Return detailed information about a specific project"""
        try:
            # Path manipulation to ensure security (no directory traversal)
            if '..' in project_path:
                self.send_error_response('Invalid project path', 400)
                return
                
            projects_dir = "/io/data"  # Path for QGIS/QGIS Server image
            full_path = ""
            
            # Check if project_path is just a project name (for standard structure)
            if not project_path.endswith('.qgs') and not project_path.endswith('.qgz'):
                # Try to find the project in a directory of the same name
                potential_qgs = os.path.join(projects_dir, project_path, f"{project_path}.qgs")
                potential_qgz = os.path.join(projects_dir, project_path, f"{project_path}.qgz")
                
                if os.path.exists(potential_qgs):
                    full_path = potential_qgs
                    project_path = os.path.join(project_path, f"{project_path}.qgs")
                elif os.path.exists(potential_qgz):
                    full_path = potential_qgz
                    project_path = os.path.join(project_path, f"{project_path}.qgz")
                else:
                    # Not found in standard structure, might be a direct file reference
                    full_path = os.path.join(projects_dir, project_path)
            else:
                # Direct file reference
                full_path = os.path.join(projects_dir, project_path)
            
            # Check if file exists
            if not os.path.exists(full_path):
                self.send_error_response('Project not found', 404)
                return
                
            # Load the project and extract information
            temp_project = QgsProject()
            if not temp_project.read(full_path):
                self.send_error_response('Failed to read project file', 500)
                return
            
            # Get project name without extension
            project_name = os.path.splitext(os.path.basename(full_path))[0]
            
            # Check if the project is in a directory of the same name (standard structure)
            parent_dir = os.path.dirname(project_path)
            is_standard_structure = (os.path.basename(parent_dir) == project_name)
                
            # Extract project information
            info = {
                'title': temp_project.title() or project_name,
                'fileName': os.path.basename(full_path),
                'path': project_path,
                'apiUrl': f"/api/projects/{project_path}",
                'serviceUrl': f"/api/projectinfo/{project_name}" if is_standard_structure else None,
                'modified': os.path.getmtime(full_path),
                'projection': {
                    'authid': temp_project.crs().authid(),
                    'description': temp_project.crs().description()
                }
            }
            
            # Add layer information
            info['layers'] = []
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
                
            # Add layout information
            info['layouts'] = []
            for layout in temp_project.layoutManager().layouts():
                layout_info = {
                    'name': layout.name(),
                    'width': layout.paperWidth(),
                    'height': layout.paperHeight()
                }
                info['layouts'].append(layout_info)
                
            # Add WMS/WFS capabilities URLs if using standard structure
            if is_standard_structure:
                info['services'] = {
                    'wms': f"/api/projectinfo/{project_name}?SERVICE=WMS&REQUEST=GetCapabilities",
                    'wfs': f"/api/projectinfo/{project_name}?SERVICE=WFS&REQUEST=GetCapabilities"
                }
                
            self.send_json_response(info)
            
        except Exception as e:
            log_message(f"Error handling project details request: {str(e)}", Qgis.Critical)
            self.send_error_response(str(e), 500)

    def send_json_response(self, data):
        """Send a JSON response by overriding the current response"""
        handler = self.server_iface.requestHandler()
        handler.clear()
        handler.setResponseHeader('Content-Type', 'application/json')
        handler.setResponseHeader('Access-Control-Allow-Origin', '*')
        
        # Convert data to JSON byte string
        json_data = json.dumps(data, indent=2).encode('utf-8')
        
        # Stop further request processing
        handler.appendBody(json_data)
        
    def send_error_response(self, message, status=404):
        """Send an error response"""
        handler = self.server_iface.requestHandler()
        handler.clear()
        handler.setResponseHeader('Content-Type', 'application/json')
        handler.setResponseHeader('Access-Control-Allow-Origin', '*')
        handler.setResponseHeader('Status', f"{status} Error")
        
        error_data = {
            'error': True,
            'message': message,
            'status': status
        }
        
        handler.appendBody(json.dumps(error_data, indent=2).encode('utf-8'))

class ProjectInfoServer:
    """QGIS Server Plugin implementation"""
    
    def __init__(self, server_iface):
        self.server_iface = server_iface
        self.filter = ProjectInfoFilter(server_iface)
        
        # Register the filter with QGIS Server
        server_iface.registerFilter(self.filter, 100)
        
        # Log plugin startup
        log_message('ProjectInfo plugin loaded and filter registered')

def serverClassFactory(server_iface):
    """
    Class factory for QGIS Server Plugin
    
    :param server_iface: A QGIS Server Interface instance.
    :type server_iface: QgsServerInterface
    """
    try:
        log_message("Loading ProjectInfo plugin")
        return ProjectInfoServer(server_iface)
    except Exception as e:
        log_message(f"Error initializing ProjectInfo plugin: {str(e)}", Qgis.Critical)
        return None