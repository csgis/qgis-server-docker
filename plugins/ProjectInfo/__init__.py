# -*- coding: utf-8 -*-
"""
 QGIS Server Plugin: ProjectInfo
 Provides a JSON endpoint for QGIS Server project information
"""

import os
import json
import traceback
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
        """Called when request is ready"""
        # We don't handle the request here, we wait for responseReady
        pass
        
    def sendResponse(self):
        """Called when response is ready to be sent"""
        # We don't modify the server's response
        pass
        
    def responseReady(self):
        """Called when response has been prepared but not yet sent"""
        request = self.server_iface.requestHandler().requestMethod()
        params = self.server_iface.requestHandler().parameterMap()
        
        # Check if this is a request for our service
        service = params.get('SERVICE', '').upper()
        if service != 'PROJECTINFO':
            return
            
        # Log that we're handling it
        log_message(f"Handling ProjectInfo request: {params}")
        
        # Capture the response
        req_param = params.get('REQUEST', '').upper()
        try:
            if req_param == 'GETPROJECTS':
                self.get_projects()
                return
                
            elif req_param == 'GETPROJECTDETAILS':
                project_path = params.get('PROJECT', '')
                if project_path:
                    self.get_project_details(project_path)
                    return
                else:
                    self.send_error_response("Missing PROJECT parameter", 400)
                    return
                    
            # Default action is to list projects
            self.get_projects()
            
        except Exception as e:
            log_message(f"Error handling ProjectInfo request: {str(e)}", Qgis.Critical)
            log_message(traceback.format_exc(), Qgis.Critical)
            self.send_error_response(str(e), 500)
        
    def get_projects(self):
        """Return list of all available projects"""
        try:
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
                try:
                    info = {
                        'title': os.path.splitext(os.path.basename(project_file))[0],
                        'path': project_file,
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
            log_message(traceback.format_exc(), Qgis.Critical)
            self.send_error_response(str(e), 500)

    def get_project_details(self, project_path):
        """Return detailed information about a specific project"""
        try:
            # Path manipulation to ensure security (no directory traversal)
            if '..' in project_path:
                self.send_error_response('Invalid project path', 400)
                return
                
            # Get full path
            projects_dir = self.get_projects_directory()
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
                
            # Extract project information
            info = {
                'title': temp_project.title() or os.path.splitext(os.path.basename(full_path))[0],
                'fileName': os.path.basename(full_path),
                'path': project_path,
                'modified': os.path.getmtime(full_path),
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
                
            # Add layout information
            info['layouts'] = []
            for layout in temp_project.layoutManager().layouts():
                layout_info = {
                    'name': layout.name(),
                    'width': layout.paperWidth(),
                    'height': layout.paperHeight()
                }
                info['layouts'].append(layout_info)
                
            self.send_json_response(info)
            
        except Exception as e:
            log_message(f"Error handling project details request: {str(e)}", Qgis.Critical)
            log_message(traceback.format_exc(), Qgis.Critical)
            self.send_error_response(str(e), 500)
            
    def get_projects_directory(self):
        """Get the directory containing QGIS projects"""
        # Try multiple possible locations for the projects directory
        candidates = [
            # Environment variables
            os.environ.get('QGIS_SERVER_PROJECTS_DIR'),
            # Landing page setting (split first entry if exists)
            os.environ.get('QGIS_SERVER_LANDING_PAGE_PROJECTS_DIRECTORIES', '').split('||')[0] 
                if os.environ.get('QGIS_SERVER_LANDING_PAGE_PROJECTS_DIRECTORIES') else None,
            # Camptocamp default
            '/project'
        ]
        
        # Use the first path that exists
        for path in candidates:
            if path and os.path.exists(path):
                log_message(f"Using projects directory: {path}")
                return path
                
        # If no directory exists, use a default
        default_dir = '/tmp/qgis_projects'
        log_message(f"No valid projects directory found, using default: {default_dir}", Qgis.Warning)
        
        # Create the directory if it doesn't exist
        if not os.path.exists(default_dir):
            os.makedirs(default_dir)
            
        return default_dir

    def send_json_response(self, data):
        """Send a JSON response by overriding the current response"""
        handler = self.server_iface.requestHandler()
        handler.clear()
        handler.setResponseHeader('Content-Type', 'application/json')
        handler.setResponseHeader('Access-Control-Allow-Origin', '*')
        handler.appendBody(json.dumps(data, indent=2).encode('utf-8'))
        
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
        log_message(traceback.format_exc(), Qgis.Critical)
        return None