# -*- coding: utf-8 -*-
"""
 QGIS Server Plugin: ProjectInfo
 Provides a JSON endpoint for QGIS Server project information
"""

import os
import json
from qgis.server import (
    QgsServerOgcApi,
    QgsServerOgcApiHandler,
    QgsServerRequest,
    QgsServerInterface
)
from qgis.core import (
    QgsProject,
    QgsMessageLog,
    Qgis
)

def log_message(message, level=Qgis.Info):
    """Helper to log messages"""
    QgsMessageLog.logMessage(message, 'ProjectInfo Plugin', level)

class ProjectInfoApi(QgsServerOgcApi):
    """ProjectInfo API implementation"""

    def __init__(self, server_iface):
        super().__init__(
            server_iface,
            '/projectinfo',
            'Project Information API',
            'API to get information about QGIS projects',
            '1.0.0'
        )
        
        # Register API handlers
        self.register_handler(ProjectsHandler(server_iface))
        self.register_handler(ProjectDetailsHandler(server_iface))
        
        log_message("ProjectInfo API initialized at /projectinfo")


class ProjectsHandler(QgsServerOgcApiHandler):
    """Handler for /projects endpoint"""
    
    def __init__(self, server_iface):
        super().__init__()
        self.server_iface = server_iface
        
    def path(self):
        """API endpoint path"""
        return "/projects"
        
    def description(self):
        """Handler description"""
        return "Get list of available QGIS projects"
        
    def operationId(self):
        """Operation ID"""
        return "getProjects"
        
    def linkTitle(self):
        """Link title in API description"""
        return "Projects List"
        
    def linkType(self):
        """Link relation type"""
        return "projects"
        
    def handleRequest(self, context):
        """Handle the request and return the response"""
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
            
            return self.createJsonResponse(result)
            
        except Exception as e:
            log_message(f"Error handling projects request: {str(e)}", Qgis.Critical)
            return self.createJsonResponse(
                {'error': str(e)},
                status=500
            )
            
    def get_projects_directory(self):
        """Get the directory containing QGIS projects"""
        # Try multiple possible locations for the projects directory
        candidates = [
            # Environment variables
            os.environ.get('QGIS_SERVER_PROJECTS_DIR'),
            # Landing page setting
            os.environ.get('QGIS_SERVER_LANDING_PAGE_PROJECTS_DIRECTORIES', '').split('||')[0],
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


class ProjectDetailsHandler(QgsServerOgcApiHandler):
    """Handler for /projects/{id} endpoint"""
    
    def __init__(self, server_iface):
        super().__init__()
        self.server_iface = server_iface
        
    def path(self):
        """API endpoint path"""
        return "/projects/{id}"
        
    def description(self):
        """Handler description"""
        return "Get detailed information about a specific QGIS project"
        
    def operationId(self):
        """Operation ID"""
        return "getProjectDetails"
        
    def linkTitle(self):
        """Link title in API description"""
        return "Project Details"
        
    def linkType(self):
        """Link relation type"""
        return "project"
        
    def handleRequest(self, context):
        """Handle the request and return the response"""
        try:
            # Get the project ID (path) from the URL
            project_id = context.matchedPath()['id']
            log_message(f"Requested project details for: {project_id}")
            
            # Path manipulation to ensure security (no directory traversal)
            if '..' in project_id:
                return self.createJsonResponse(
                    {'error': 'Invalid project path'},
                    status=400
                )
                
            # Get full path
            projects_dir = self.get_projects_directory()
            project_path = os.path.join(projects_dir, project_id)
            
            # Check if file exists
            if not os.path.exists(project_path):
                return self.createJsonResponse(
                    {'error': 'Project not found'},
                    status=404
                )
                
            # Load the project and extract information
            temp_project = QgsProject()
            if not temp_project.read(project_path):
                return self.createJsonResponse(
                    {'error': 'Failed to read project file'},
                    status=500
                )
                
            # Extract project information
            info = {
                'title': temp_project.title() or os.path.splitext(os.path.basename(project_path))[0],
                'fileName': os.path.basename(project_path),
                'path': project_id,
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
                
            # Add layout information
            info['layouts'] = []
            for layout in temp_project.layoutManager().layouts():
                layout_info = {
                    'name': layout.name(),
                    'width': layout.paperWidth(),
                    'height': layout.paperHeight()
                }
                info['layouts'].append(layout_info)
                
            return self.createJsonResponse(info)
            
        except Exception as e:
            log_message(f"Error handling project details request: {str(e)}", Qgis.Critical)
            return self.createJsonResponse(
                {'error': str(e)},
                status=500
            )
            
    def get_projects_directory(self):
        """Get the directory containing QGIS projects"""
        # Try multiple possible locations for the projects directory
        candidates = [
            # Environment variables
            os.environ.get('QGIS_SERVER_PROJECTS_DIR'),
            # Landing page setting
            os.environ.get('QGIS_SERVER_LANDING_PAGE_PROJECTS_DIRECTORIES', '').split('||')[0] if os.environ.get('QGIS_SERVER_LANDING_PAGE_PROJECTS_DIRECTORIES') else None,
            # Camptocamp default
            '/project'
        ]
        
        # Use the first path that exists
        for path in candidates:
            if path and os.path.exists(path):
                return path
                
        # If no directory exists, use a default
        default_dir = '/tmp/qgis_projects'
        
        # Create the directory if it doesn't exist
        if not os.path.exists(default_dir):
            os.makedirs(default_dir)
            
        return default_dir
        

def serverClassFactory(server_iface):
    """
    Class factory for QGIS Server Plugin
    
    :param server_iface: A QGIS Server Interface instance.
    :type server_iface: QgsServerInterface
    """
    try:
        log_message("Loading ProjectInfo plugin")
        return ProjectInfoApi(server_iface)
    except Exception as e:
        log_message(f"Error initializing ProjectInfo plugin: {str(e)}", Qgis.Critical)
        return None