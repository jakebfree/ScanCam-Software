import sys
from time import time, gmtime
import math
from socket import gethostname
from os import getcwd, chdir

import zaber.zaber_device as zaber_device

import logging, idscam.common.syslogger

log = idscam.common.syslogger.get_syslogger('scancam')


MAX_CLIP_LENGTH = 60                    # seconds
MAX_Z_MOVE_SPEED = 3.0                  # mm/second
STANDARD_Z_SPEED = 1.0                  # mm/second
video_location = "/home/freemajb/data/scancam_proto_videos/"
verbose_for_scan_build = False



class ScanBase():
        '''ScanBase(id = None, video_params = None)

        Implements the scan base class.

        id:             A user-defined string for this scan. If no id is passed then a
                        string representation of the hash of this instance is used

        video-params:   Dictionary containing optional camera video parameters such as:
                        binning, subsampling, cropping, exposure window. If none are
                        specified the camera will use its default values.
        
        Each scan is a sequential list of dictionaries, each of which represents a single
        scan point. Each point must minimally include 'x' and 'y' keys.

        The dictionaries may optionally also include the following keys:
           'z0' -      The depth setting for a given scan point. When used with 'z1', the
                       camera can also be used to record video while walking through the
                       depth of a culture. In these cases, the scan will alternate walking
                       from z0 to z1 and from z1 to z0.
           'z1' -      The second depth setting when imaging through the culture depth
           't'  -      Time duration in seconds of the video clip at a given point. Also used
                       to adjust the speed of the z-move during imaging through the culture
                       depth to match the z move to cooincide with the video duration.
           'point-id'- User-defined identifier for the point. Defaults to sequential integers
                       for most scan builders.
                       

        There are three types of time values for a scan point.
               no 't' key:     Skip z1 move and all video calls. This may be used for intermediate
                               scan points that don't require video
               t = 0:          Place-holder for taking an image instead of video.
               t > 0:          Video clip duration. Also used to determine z-speed during move to z1
        '''

        def __init__(self, id = None, video_format_params = None):
                if id == None:
                        id = str(hash(self))
                self.id = id

                # TODO: Compare video params keys against valid camera options?
                self.video_format_params = video_format_params
                
                self.scanpoints = []

        def get_id(self):
                '''ScanBase.get_id()

                Returns string containing scan identifier.
                '''
                return self.id

        def log_scan_contents(self, logger, log_level):
                '''ScanBase.log_scan_contents(logger, log_level)
                
                Print the contents of the scan to logger.
                '''
                logger.log(log_level, "Scan ID: " + self.id)
                for point in self.scanpoints:
                        logger.log(log_level, "    " + str(point))

        def build_scan_from_target_origins(self, origins, target_width = 19.1, target_height = 26.8,
                                           num_h_scan_points = 1, num_v_scan_points = 1, just_corners = False,
                                           always_start_z0 = False, verbose = False):
                '''ScanBase.build_xyz_scan_from_target_origins( origins, target_width = 19.1, target_height = 26.8,
                                num_h_scan_points = 1, num_v_scan_points = 1, just_corners = False, 
                                alwasys_start_z0 = False, verbose = False)

                origins:        List of dictionaries each of which represents the bottom-left corner of the target
                                area. In the format:
                                {'x'=<>, 'y'=<>, 'area_id'=<>}

                target_width:   Width (in mm) of the target areas to scan over

                target_height:  Height (in mm) of the target areas to scan over

                num_h_scan_points:  Number of scan points across each target area

                num_v_scan_points:  Number of scan points down each target area

                just_corners:   Boolean that when true creates a scan consisting only of the four
                                corner scan points of each area that would be created given the other
                                args. It may be useful for verifying the x-y calibration of the scan
                                since the edges of the wells are likely to be visible in the camera FOV

                always_start_z0:  Option that disables alternating the starting z value between z0 and
                                z1. This may be desired when you want a correlation between the z value
                                and the elapsed time in the video clip such as during depth calibration.

                verbose:        Verbosity
                
                
                Builds an scan of points across a list of equally sized rectangular targets.

                The scan begins at the origin (corner of target area with smallest X and Y values) of 
                the first target and scans across and up it in an ess pattern that goes in a positive X 
                direction across a row and negative X direction back across the next row. It then jumps 
                to the origin of the next target and scans it. Repeating until all of the targets are 
                complete.

                It has no knowledge of the camera's field of view so the user must designate the correct
                number of horizontal and vertical scan points to achieve the correct step-over distances.

                The scan points alternate between starting with the given z0 and z1 in order to avoid
                the extra z-axis move back to z0 for each point. This behavior may be disabled by
                setting always_start_z0 to True.

                t values are constant for each target and assigned to all scan points
                '''
        
                cell_width = target_width/float(num_h_scan_points)
                cell_height = target_height/float(num_v_scan_points)

                # Iterate across rows and up columns to scan each target
                self.scanpoints = []
                first_z_last_time = ''
                area_num = 0
                for origin in origins:
                        area_num += 1
                        # The center of the first cell isn't the corner, it's half a cell over (and up)
                        x0 = origin['x'] + cell_width/2.0
                        y0 = origin['y'] + cell_height/2.0
                        for jj in range(num_v_scan_points):
                                for ii in range(num_h_scan_points):
                                        scan_point = {}
                                        
                                        # It is useful for location calibration to be able to find the corners of the
                                        # wells. So with a True just_corners value we adjust the algorithm to skip all
                                        # locations except the four corners of the area.
                                        if not just_corners:
                                                i = ii
                                                j = jj
                                        else:
                                                i = ii*(num_h_scan_points-1)
                                                j = jj*(num_v_scan_points-1)
                                                if ii > 1 or jj > 1:
                                                        break

                                        # Count even rows up and odd rows down to skip track back to 0
                                        if j%2 == 0:
                                                scan_point['x'] = x0 + i*cell_width
                                        if j%2 == 1:
                                                scan_point['x'] = x0 + (num_h_scan_points-1-i)*cell_width

                                        scan_point['y'] = y0 + j*cell_height

                                        # If the always_start_z0 flag is true, spoof the tracking flag to always 
                                        # start with the origin point's z0 value
                                        if always_start_z0 == True:
                                                first_z_last_time = 'z1'

                                        # If there is a second z-axis value, alternate which one you
                                        # start with to avoid waiting for z to get back to z0 every time
                                        if origin.has_key('z1'):
                                                if first_z_last_time != 'z0':
                                                        scan_point['z0'] = origin['z0']
                                                        scan_point['z1'] = origin['z1']
                                                        first_z_last_time = 'z0'
                                                else:
                                                        scan_point['z0'] = origin['z1']
                                                        scan_point['z1'] = origin['z0']
                                                        first_z_last_time = 'z1'
                                        # If there's no second z value, just use the one you have
                                        else:
                                                if scan_point.has_key('z0'):
                                                        scan_point['z0'] = origin['z0']
                                                        
                                        # Add cell identifier
                                        if origin.has_key('area-id'):
                                                area_id = origin['area-id']
                                        else:
                                                area_id = str(area_num)
                                        scan_point['point-id'] = "%s-%d-%d" % ( area_id, j+1, i+1)

                                        # Assign target areas id to point. This may be useful later when
                                        # calibrating in cases where a given calibration is to be applied
                                        # to all points in a target area. If none given, serialize.
                                        if origin.has_key('area-id'):
                                                scan_point['area-id'] = origin['area-id']
                                        else:
                                                scan_point['area-id'] = area_num
                                                
                                        # Propagate any items that we haven't explicitly handled through
                                        # from the origin to this point. Likely to include t 
                                        for key in origin:
                                                if not scan_point.has_key(key):
                                                        scan_point[key] = origin[key]

                                        # We're done with that point, add it to the new scan
                                        self.scanpoints.append( scan_point )
                                        if verbose: print "Appended " + str(scan_point)




                
class SixWellBioCellScan(ScanBase):
        '''SixWellBioCellScan(starting_origin, rotations_orientation_id, scan_id=None, 
                        num_h_scan_points=1, num_v_scan_points=1, clip_duration = 10, 
                        just_corners=False, always_start_z0=False, verbose=False)

        Takes the origin of the corner well and generates a scan based on the known 
        geometry of the 6-well plate as measured from the SolidWorks model. The corner
        well given must be the one with the minimum X and Y coordinates.

        starting_origin:        Coordinates of corner of the well with the least X and 
                                Y coordinate values: {'x':<>, 'y':<>}
                                
        rotation_orientation_id:  String identifier that denotes which way the plate
                                is oriented. Only two orientations are supported. Both 
                                have the long axis of the plate in the Y direction. The 
                                A1 cell may be in the bottom-left or top-right position

        scan_id:                User-defined string identifier of the scan

        num_h_scan_points:      Number of scan points across each well

        num_v_scan_points:      Number of scan points down each well
        
        clip_duration:          Duration in seconds to record video for each scan point

        video_format_params:    Dictionary of video params to be passed to camera when
                                recording video clips

        just_corners:           Boolean that when true creates a scan consisting only of the four
                                corner scan points of each area that would be created given the other
                                args. It may be useful for verifying the x-y calibration of the scan
                                since the edges of the wells are likely to be visible in the camera FOV

        always_start_z0:        Option that disables alternating the starting z value between z0 and
                                z1. This may be desired when you want a correlation between the z value
                                and the elapsed time in the video clip such as during depth calibration.

        verbose:                Verbose

        Assumes that the orientation of the plate is such that it is vertical
        (long axis of plate and wells is in y-direction) and the top-left well is
        higher than the top-right well.
        '''
                        

        def __init__(self,
                     starting_origin,
                     rotation_orientation_id,
                     scan_id = None,
                     num_h_scan_points = 1,
                     num_v_scan_points = 1,
                     clip_duration = None,
                     video_format_params = None,
                     just_corners = False,
                     always_start_z0 = False,
                     verbose = False):

                self.calibrated_for_z = False

                ScanBase.__init__(self, scan_id, video_format_params)

                well_origins = self.generate_well_origins( starting_origin, rotation_orientation_id )

                ScanBase.build_scan_from_target_origins(self,
                                                         well_origins,
                                                         target_width = 19.1,
                                                         target_height = 26.8,
                                                         num_h_scan_points = num_h_scan_points,
                                                         num_v_scan_points = num_v_scan_points,
                                                         just_corners = just_corners,
                                                         always_start_z0 = always_start_z0,
                                                         verbose = verbose )

                if clip_duration == None:
                        return

                # Add the video clip duration for each point
                for scanpoint in self.scanpoints:
                        scanpoint['t'] = clip_duration

        def generate_well_origins( self, starting_well_origin, rotation_orientation_id ):
                '''generate_well_origins( starting_well_origin )

                Given the origin of the top-left well of a six well plate, generate a list
                of all six well origins. The origins are the bottom left corners of the wells.
                Each well is given an area-id based on the rotation_orientation_id.

                starting_well_origin:   (x,y) coordinates of the origin of the top-left well

                rotation_orientation_id:  String identifier that denotes which way the plate
                                        is oriented. Only two orientations are supported. Both 
                                        have the long axis of the plate in the Y direction. The 
                                        A1 cell may be in the bottom-left or top-right position
                '''
                # These were calculated from a list of well corners measured from the SolidWorks model
                # The area_ids are designated based on the 6-well biocell assembly procedure OPM-A426-AP-B.pdf
                self.delta_origins = {}
                self.delta_origins['1'] = [     {'y': 0.0, 'x': 0.0, 'area-id': 'B1'},
                                                {'y': 38.3, 'x': 0.0, 'area-id': 'B2'},
                                                {'y': 76.6, 'x': 0.0, 'area-id': 'B3'},
                                                {'y': -8.7, 'x': 28.1, 'area-id': 'A1'},
                                                {'y': 29.6, 'x': 28.1, 'area-id': 'A2'},
                                                {'y': 67.9, 'x': 28.1, 'area-id': 'A3'}    ]
                self.delta_origins['2'] = [     {'y': 0.0, 'x': 0.0, 'area-id': 'A3'},
                                                {'y': 38.3, 'x': 0.0, 'area-id': 'A2'},
                                                {'y': 76.6, 'x': 0.0, 'area-id': 'A1'},
                                                {'y': -8.7, 'x': 28.1, 'area-id': 'B3'},
                                                {'y': 29.6, 'x': 28.1, 'area-id': 'B2'},
                                                {'y': 67.9, 'x': 28.1, 'area-id': 'B1'}    ]

                # Build list of well origins from origin of top-left well and deltas
                well_origins = []
                for delta_origin in self.delta_origins[rotation_orientation_id]:
                        origin = {'x': (starting_well_origin['x']+delta_origin['x']), 
                                  'y': (starting_well_origin['y']+delta_origin['y']),
                                  'area-id': delta_origin['area-id'] 
                                 }
                        # Copy any other dictionary pairs in the starting_well_origin that we
                        # aren't explicitly handling. This is likely to include t and z values.
                        for key in starting_well_origin:
                                if not origin.has_key(key):
                                        origin[key] = starting_well_origin[key]

                        well_origins.append( origin )

                return well_origins



def xtz2xyz(xtz, arm_length = 55.0):
        '''xthetaz2xyz( xtz, arm_length = 55.0 )

        Convert a {'X':<>, 'theta':<> } point to a { 'x':<> 'y':<>} point
        If the passed dict has z0, z1, and/or t keys, the values are copied over
        '''
        
        xyz = {}
        xyz['x'] = xtz['X'] - math.sin( math.radians(xtz['theta']) ) * arm_length
        xyz['y'] = -math.cos( math.radians(xtz['theta']) ) * arm_length

        # Propagate all other members through to xyz scan
        for param in xtz:
                if param in ('x', 'y'):
                        continue
                xyz[param] = xtz[param]

        return xyz

                

################################################################################



class ScanCamBase():
        '''ScanCamBase(stages, camera, scancam_id = None, camera_warmup = 0.0, stage_timeout = 100)

        Base class for scacncams.

        stages:         Dictionary of zaber_devices that comprise the scancam.
                        The keys are the axis identifiers. (e.g. 'X', 'theta',
                        'z')

        camera:         Camera class derived from CameraBase
        
        scancam_id:     Identifier string for class

        camera_warmup:  Seconds that it takes to warm up camera. Used to calculate second
                        depth move speed so that the move fudges closer to the clip duration

        stage_timeout:  Number of seconds to wait for stage moves before timing out.
        '''


        def __init__(self, stages, camera, scancam_id = None, camera_warmup = 0.0, stage_timeout = 100, target_video_dir = None):

                self.stages = stages
                self.camera = camera
                if scancam_id == None:
                        scancam_id = str(hash(self))
                self.id = scancam_id
                self.camera_warmup = camera_warmup
                self.stage_timeout = stage_timeout
                if target_video_dir == None:
                        # Default to current directory if none given
                        self.target_video_dir = getcwd()
                else:
                        self.target_video_dir = target_video_dir
                self.stow_location = None

        def get_id(self):
                '''get_id()

                Returns identifier string for this scancam instance. If none was
                given during construction, it defaults to a hash of the object
                at that time.
                '''
                return self.id


        def wait_for_stages_to_complete_actions(self):
                '''ScanCamBase.wait_for_stages_to_complete_actions()

                For each scancam stage, wait until .in_action() returns False, and timeout
                if it takes too long.
                '''
                # TODO: Fix timing such that if takes first stage X seconds to
                # get to its target then next stage doesn't have a cumulative
                # wait of up to X + timeout_secs
                try:
                        for stage in self.stages.values():
                                stage.wait_for_action_to_complete( self.stage_timeout )
                except zaber_device.DeviceTimeoutError, stage_id:
                        # If one device times out, stop all of them
                        self.stop()
                        raise


        def build_timestring(self, t):
                '''ScanCamBase.build_timestring(time)

                Build timestring in the format:
                        YYYY-MM-DD_HH-MM-SS

                t:   Time value in seconds past the epoch
                '''
                return "%04d-%02d-%02d_%02d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)

                
        def stop(self):
                '''ScanCamBase.stop()

                Send stop command to all stages.
                '''
                for stage in self.stages.values():
                        stage.stop()


        def home(self):
                '''ScanCamBase.home()

                Send home command to all stages and wait to complete
                '''
                for stage in self.stages.values():
                        stage.home()
                        stage.step()

                try:
                        self.wait_for_stages_to_complete_actions()
                except zaber_device.DeviceTimeoutError, device_id:
                        log.warning("Device %d timed out during homing" % device_id)
                        raise


        def move_stages(self, stage_targets, wait_for_completion = True):
                '''ScanCamBase.move_stages(stage_targets, wait_for_move_to_complete = True)

                Move as many stages as are specified in the scanpoint and wait
                until they complete the moves or timeout.

                stage_targets:  Dictionary of stage targets. Keys are the stage
                                ids. Values are the stage targets in scientific
                                units.

                wait_for_move_to_complete:  If true wait until all devices are
                                no longer active before returning.
                '''
                for stage_id in stage_targets:
                        # Enqueue scan point move commands
                        self.stages[stage_id].move_absolute( stage_targets[stage_id] )

                for stage_id in stage_targets:
                        # Step to next queued scan point for all axes
                        self.stages[stage_id].step()

                # Return if we don't have to wait for the moves
                if not wait_for_completion: return
                
                # Wait for all moves to complete
                try:
                        self.wait_for_stages_to_complete_actions()
                except zaber_device.DeviceTimeoutError, device_id:
                        log.critical("Device %d timed out during move for scan point %d" % (device_id, scan_point_num))
                        raise


        def in_action(self):
                '''ScanCamBase.in_action()

                Return true if one or more devices is in action.
                '''
                in_action = False
                for stage in self.stages:
                        in_action = in_action or self.stages[stage].in_action()
                return in_action
        

        def scan_action(self, xyz_scan):

                scan_point_num = 0
                for point in xyz_scan.scanpoints:

                        scan_point_num += 1
                        log.debug("Step " + str(scan_point_num) + " " + str(point))

                        # Start to build the move setting for this scan point
                        move_setting = {'x': point['x'],
                                        'y': point['y']}

                        # Add z target if required
                        if point.has_key('z0'):

                                # If there is a second z-axis value, then we want to record video while moving through the
                                # depth of the subject (z-axis). 
                                if point.has_key('z1'):
                                        # The move from z0 to z1 should take the same amount of time as the video clip duration
                                        z1_speed = abs(point['z1']-point['z0']) / (float(point['t']))

                                        if z1_speed > MAX_Z_MOVE_SPEED:
                                                log.error( str(target_z_speed) + " is faster than the maximum speed: %f" % MAX_Z_MOVE_SPEED)
                                                raise ValueError

                                        # But, the camera may require a warm-up time from system call to the first frame.
                                        # The camera warm-up time may even be a significant fraction of the clip-duration, and we
                                        # need to block on the camera call due to the variability in compression time. So we
                                        # are stuck not able to wait to start the move because we will already be blocking 
                                        # on the camera

                                        # The hack is to back up and take a running start. We adjust the z0 to be further from z1
                                        # than specified and time it so that we will be at the desired z0 location when the 
                                        # video starts.
                                        if point['z0'] < point['z1']:
                                                move_setting['z'] = point['z0'] - z1_speed * self.camera_warmup 
                                        else:   
                                                move_setting['z'] = point['z0'] + z1_speed * self.camera_warmup 

                                else:
                                        move_setting['z'] = point['z0']

                                # Set z-axis speed to standard moderately fast value. It may have been set to a
                                # different value during an image-through-depth sequence
                                self.stages['z'].set_target_speed_in_units( STANDARD_Z_SPEED, 'T-series' )

                        # Move to x,y,z
                        log.debug( "Moving to " + str(move_setting) )
                        self.move( move_setting )
                        

                        # If this scan point has no time value, there is no video to record
                        # Probably a transitional point that is just there to avoid crashing
                        # into walls.
                        if not point.has_key('t'):
                                log.info("Point has no time value. Skipping z1 and video")
                                continue
                        
                        # Start z1 move
                        if point.has_key('z1'):
                                self.stages['z'].set_target_speed_in_units( z1_speed, 'T-series' )
                                move_setting = {'z': point['z1']}
                                self.move( move_setting, wait_for_completion = False )

                      
                        # Build video file target basename in the format:
                        #       <payload>_<scan definition ID>_<scan point ID>.<YYYY-MM-DD_HH-mm-SS>.h264
                        t_str = self.build_timestring( gmtime(time()) )
                        filename_base = gethostname() + '_' + xyz_scan.get_id() + '_'
                        if point.has_key('point-id'):
                                filename_base += point['point-id'] + '.' + t_str
                        else:
                                filename_base += str(scan_point_num) + '.' + t_str

                        # Change working directory so that video are placed in correct spot
                        try:
                                chdir( self.target_video_dir ) 
                        except OSError:
                                log.warning("Invalid video target directory. Exiting.")
                                sys.exit(-1)
                                
                        # Record Video                        
                        try:
                                self.camera.record_video(filename_base, int(point['t']), xyz_scan.video_format_params)
                        except KeyboardInterrupt:
                                raise        
                        except:
                                raise

                        # Assure that the last z-axis move was completed
                        try:
                                self.wait_for_stages_to_complete_actions()
                        except zaber_device.DeviceTimeoutError, device_id:
                                log.warning("Device %d timed out during second z move on scan point %d" % (device_id, scan_point_num))
                                raise

class XThetaZScanCam(ScanCamBase):
        '''XThetaZScanCam(self, stages, arm_length = 52.5, min_X = 0.0, max_X = 176.0, camera_warmup = 0.0, stage_timeout = 100)

        Scancam with 200mm x-axis, rotary stage, and 10mm z-axis. The z-axis and
        camera are mounted to the rotary axis and can swing around to where the
        camera nearly collides with the floor of CGBA. The camera FOV rotates
        with the stage.

        stages:         List of the three zaber devices that comprise the scancam
                        hardware. Constructor uses the Zaber device hardware ids
                        to assign stage identifiers.

        arm_length:     Distance between the axis of rotation and the camera
                        viewing axis. Is used to translate between the x,y coord
                        spec'd in a scan and the required X and theta commands

        min_X:          Minimum acceptable setting for the X-axis.

        max_X:          Maximum acceptable setting for the X-axis.

        camera_warmup:  Seconds that it takes to warm up camera. Used to calculate second
                        depth move speed so that the move fudges closer to the clip duration

        stage_timeout:  Number of seconds to wait for stage moves before timing out.
        '''

        def __init__(self, stages, camera = None, arm_length = 52.5, min_X = 0.0, max_X = 176.0, 
                     camera_warmup = 0.0, stage_timeout = 100, target_video_dir = None):

                self.arm_length = arm_length
                self.min_X = min_X
                self.max_X = max_X

                # TODO: Import hardware id to stage id mapping and use to build stage dict
                xtz_stages = {}
                xtz_stages['X'] = stages[0]
                xtz_stages['theta'] = stages[1]
                xtz_stages['z'] = stages[2]

                ScanCamBase.__init__(self, xtz_stages, camera, camera_warmup = camera_warmup, 
                                     stage_timeout = stage_timeout, target_video_dir = target_video_dir)

                self.used_negative_of_angle_last_time = False                


        def xy2xtheta(self, xy_point):
                '''XThetaZScanCam.xy2xtheta(xy_point)

                Use physical geometry of the scancam to translate from a
                cartesian xy coord point (in mm) to the one implemented by our
                X-theta hardware where X is the X-stage setting in mm and theta
                is the rotary axis setting in degrees.

                xy_point:       Dictionary containing the x and y values for the
                                scan point. Only the 'x' and 'y' keys are used
                                by this functions, but other may be included.

                Returns:        Dictionary in the format:
                                        {'X': <x-axis value>, 'theta': <rotary-axis value>}
                '''
                
                x = xy_point['x']
                y = xy_point['y']

                # Calculate X-theta Coordinates
                # There are regions (closer to X=0) where the arm can't swing to the correct y value
                # without swinging back toward the negative X direction. The angle required for the
                # same y value but swinging back is the negative of the angle. The rotary stage cannot
                # handle negative numbers so 360 is added. Therefore, the negative of acos(y/arm) is
                # calculated as:   # 360 - acos(y/arm).
                #
                # There may be areas where a scan crosses over the edge of where it can reach using the
                # acos or must use its negative. In order to avoid swinging way around between scan points
                # when it doesn't have to, it first tries using the same type of angle (acos or its
                # negative) that it did last time in order to avoid unnecessary swings.
                past_reach = False
                if not self.used_negative_of_angle_last_time:
                        try:
                                theta = math.degrees( math.acos( float(-y)/float(self.arm_length) ))
                        except ValueError:
                                past_reach = True
                else:
                        try:
                                theta = 360 - math.degrees( math.acos( float(-y)/float(self.arm_length) ))
                        except ValueError:
                                past_reach = True
                
                # If the acos call raised an exception, the desired y-value is beyond the reach
                # of the swing arm. Set the rotary axis straight up or down to do the best you can        
                if past_reach:
                        if( y > 0 ):
                                theta = 180.0
                        else:
                                theta = 0.0
                        log.debug("Incapable of reaching location (%f, %f). Setting theta=%f" % (x, y, theta))
                
                X = x + self.arm_length * math.sin( math.radians( theta ) )

                # If the calculated X is out of bounds, swing theta to its negative (which could be back
                # to the natural acos)
                if X < self.min_X or X > self.max_X:
                        self.used_negative_of_angle_last_time = not self.used_negative_of_angle_last_time
                        theta = 360 - theta     
                        X = x + self.arm_length * math.sin( math.radians( theta ) )

                # If X is still out of bounds, it must be unachievable. Raise exception
                if X < self.min_X or X > self.max_X:
                        log.critical("Unable to translate (%f, %f) to X-theta coordinates." % (x,y))
                        log.critical("Calculated X value of %f is out of range." % X)
                        raise ValueError
                
                # Put x-theta coord in scan list
                x_theta_point = { 'X': X, 'theta': theta }
                log.debug("Converted to " + str(x_theta_point) + " from " + str(xy_point) )

                return x_theta_point


        def move(self, settings, wait_for_completion = True):
                '''XThetaZScanCam.move(settings)

                Move as many of the scancam stages as are specified in settings
                and wait until they complete or timeout.

                settings:       Dictionary with stage ids for keys and target
                                locations for values.
                '''
                xtz_setting = {}
                if settings.has_key('x') and settings.has_key('y'):
                        xtz_setting = self.xy2xtheta( {'x': settings['x'], 'y': settings['y']} )
                elif settings.has_key('x') or settings.has_key('y'):
                        log.critical("Error: Only have one of two necessary (x,y) coord needed to compute X and theta")
                        raise KeyError

                if settings.has_key('z'):
                        xtz_setting['z'] = settings['z']

                my_id = self.get_id()
                log.debug("Moving " + str(my_id) + " to " + str(xtz_setting))
                self.move_stages( xtz_setting, wait_for_completion = wait_for_completion )

        def goto_stow_position(self):
                '''XThetaZScancam.gotostow_position()

                Move stages to preset stow locations.
                '''
                target_locations = {'x': 120, 'y': 0, 'z': 5 }
                log.info("Sending stages to stow locations: " + str(target_locations) )
                self.move( target_locations )
