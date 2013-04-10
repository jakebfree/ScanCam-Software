import sys
from time import sleep, time, gmtime
import thread
import pickle
import math
import serial
import os, subprocess, shutil
try:
    import argparse
except ImportError, err:
    syslogger.critical("Failed to import argparse")
    if version_info < (2, 7):
        syslogger.critical("your are running an older version of Python. argparse was added in Python 2.7 please add library manually")
        exit(1)
    else:
        raise err

from serial_connection import *
from linear_slides import *
from rotary_stages import *
from scan_building_tools import *
from bst_camera import *

import logging, idscam.common.syslogger

log = idscam.common.syslogger.get_syslogger('scancam')


MAX_CLIP_LENGTH = 60                    # seconds
MAX_Z_MOVE_SPEED = 3.0                  # mm/second
video_location = "/home/freemajb/data/scancam_proto_videos/"
verbose_for_scan_build = False


def parse_arguments( argv ):
        # Parse config file and command line arguments
        parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
        parser.add_argument('-p', '--period', type=float, default=0.0, help="Minimum number of minutes between the start of scans. If the scan itself takes longer than the period, they will run back-to-back. Defaults to 0.")
        parser.add_argument('-l', '--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'CRITICAL'], default='INFO', help="Level of logging. Defaults to INFO")
        looping_group = parser.add_mutually_exclusive_group()
        looping_group.add_argument('-n', '--num-scans', type=int, default=1, help="Number of scans to perform before exiting. Defaults to 1")
        looping_group.add_argument('-c', '--continuous', action="store_true", help="Take scans continually without exiting")
        parser.add_argument('--home-on-start', action='store_true', default=True, help="Home all stages on startup. Only set to false during development testing to avoid long waits for home and back")
        parser.add_argument('scanfile', type=argparse.FileType('rb'), help="Scan file name. Should include a pickled list of scans.")

        # The configs group of arguments is intended to be read from a configuration file.
        # They may be overwritten at the command line (useful during development).
        # TODO: make config file location configurable
        configs = parser.add_argument_group('configs', "Arguments generally read from scancam.conf file. May be overridden at command line")
        configs.add_argument('-s', '--serial-dev', default='/dev/ttyUSB0', help="Serial device identifier. Linux example: '/dev/ttyUSB0', Windows example: 'COM1'")
        configs.add_argument('--stage-timeout', type=int, default=100, help="Number of seconds for stages to try on move before timing out")
        configs.add_argument('--camera-warmup', type=float, default=0.0, help="Time in seconds (float) between camera system call and beginning of clip. Used to adjust speed of video-through-depth z-axis move") 

        # The values are ready from the configuration file first in the list so that
        # command line arguments may supercede them if given
        args = parser.parse_args(['@scancam.conf'] + argv[1:])

        # Set up logging
        if args.log_level == 'DEBUG':
                log.setLevel(logging.DEBUG)
        elif args.log_level == 'INFO':
                log.setLevel(logging.INFO)
        elif args.log_level == 'WARNING':
                log.setLevel(logging.WARNING)
        elif args.log_level == 'CRITICAL':
                log.setLevel(logging.CRITICAL)
        else:
                print "Logging level not available. Exiting."
                sys.exit(1)

        log.critical("Logging critical messages.")
        log.error("Logging error messages")
        log.warning("Logging warning messages.")
        log.info("Logging info messages")
        log.debug("Logging debug messages")

        return args




class scan_base():
        '''scan_base(id = None, video_params = None)

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


        def log_scan_contents(self, logger, log_level):
                '''scan_base.log_scan_contents(logger, log_level)
                
                Print the contents of the scan to logger.
                '''
                logger.log(log_level, "Scan ID: " + self.id)
                for point in self.scanpoints:
                        logger.log(log_level, "    " + str(point))

        def build_scan_from_target_origins(self, origins, target_width = 19.1, target_height = 26.8,
                                           num_h_scan_points = 4, num_v_scan_points = 5, just_corners = False,
                                           verbose = False):
                '''scan_base.build_xyz_scan_from_target_origins( origins, target_width = 19.1, target_height = 26.8,
                                num_h_scan_points = 4, num_v_scan_points = 5, just_corners = False, verbose = False)

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

                verbose:        Verbosity
                
                
                Builds an scan of points across a list of equally sized rectangular targets.

                The scan begins in the bottom-left corner (origin) of the first target and scans across and up it
                in an ess pattern that goes to the right across a row and left back across the next row.
                It then jumps to the origin of the next target and scans it. Repeating until
                all of the targets are complete.

                It has no knowledge of the camera's field of view so the user must designate the correct
                number of horizontal and vertical scan points to achieve the correct step-over distances.

                The scan points alternate between starting with the given z0 and z1 in order to avoid
                the extra z-axis move back to z0 for each point.

                t values are constant for each target and assigned to all scan points
                '''
        
                cell_width = target_width/float(num_h_scan_points)
                cell_height = target_height/float(num_v_scan_points)

                # Iterate across rows and down columns to scan each target
                self.scanpoints = []
                first_z_last_time = ''
                area_num = 0
                for origin in origins:
                        area_num += 1
                        # The center of the first cell isn't the corner, it's half a cell over (and down)
                        x0 = origin['x'] - cell_width/2.0
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
                                                scan_point['x'] = x0 - i*cell_width
                                        if j%2 == 1:
                                                scan_point['x'] = x0 - (num_h_scan_points-1-i)*cell_width

                                        scan_point['y'] = y0 + j*cell_height

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
                                                        
                                        if origin.has_key('t'):
                                                scan_point['t'] = origin['t']

                                        # Add cell identifier
                                        scan_point['point-id'] = "%d-%d-%d" % ( area_num, j+1, i+1)

                                        # Assign target areas id to point. This may be useful later when
                                        # calibrating in cases where a given calibration is to be applied
                                        # to all points in a target area. If none given, serialize.
                                        if origin.has_key('area-id'):
                                                scan_point['area-id'] = origin['area-id']
                                        else:
                                                scan_point['area-id'] = area_num
                                                
                                        # We're done with that point, add it to the new scan
                                        self.scanpoints.append( scan_point )
                                        if verbose: print "Appended " + str(scan_point)




                
class six_well_biocell_scan(scan_base):
        '''6_well_biocell_scan(origin, scan_id=None, num_h_scan_points=1, num_v_scan_points=1,
                        clip_duration = 10, verbose=False)

        Takes the origin of the top-left well and generates a scan based
        on the known geometry of the 6-well plate measured from the SolidWorks model

        top_left_origin:        Bottom-left corner of the top-left well in the format
                                {'x':<>, 'y':<>}
                                
        scan_id:                User-defined string identifier of the scan

        num_h_scan_points:      Number of scan points across each well

        num_v_scan_points:      Number of scan points down each well
        
        clip_duration:          Duration in seconds to record video for each scan point

        video_format_params:    Dictionary of video params to be passed to camera when
                                recording video clips

        verbose:                Verbose

        Assumes that the orientation of the plate is such that it is vertical
        (long axis of plate and wells is in y-direction) and the top-left well is
        higher than the top-right well.
        '''
                        

        def __init__(self,
                     top_left_origin,
                     scan_id = None,
                     num_h_scan_points = 1,
                     num_v_scan_points = 1,
                     clip_duration = 3,
                     video_format_params = None,
                     verbose = False):

                self.calibrated_for_z = False

                scan_base.__init__(self, scan_id, video_format_params)

                well_origins = self.generate_well_origins( top_left_origin )

                scan_base.build_scan_from_target_origins(self,
                                                         well_origins,
                                                         target_width = 19.1,
                                                         target_height = 26.8,
                                                         num_h_scan_points = num_h_scan_points,
                                                         num_v_scan_points = num_v_scan_points,
                                                         verbose = verbose )

                for scanpoint in self.scanpoints:
                        scanpoint['t'] = clip_duration

        def generate_well_origins( self, top_left_well_origin ):
                '''generate_well_origins( top_left_well_origin )

                Given the origin of the top-left well of a six well plate, generate a list
                of all six well origins. The origins are the bottom left corners of the wells.

                top_left_well_origin:   (x,y) coordinates of the origin of the top-left well
                '''
                # These were calculated from a list of twelve well corners measured from the SolidWorks model
                self.delta_origins = [  {'y': 0.0, 'x': 0.0},
                                        {'y': 38.3, 'x': 0.0},
                                        {'y': 76.6, 'x': 0.0},
                                        {'y': 8.7, 'x': 28.1},
                                        {'y': 47.0, 'x': 28.1},
                                        {'y': 85.3, 'x': 28.1}    ]

                # Build list of well origins from origin of top-left well and deltas
                well_origins = []
                for delta_origin in self.delta_origins:
                        origin = {'x': (top_left_well_origin['x']-delta_origin['x']), 
                                  'y': (top_left_well_origin['y']-delta_origin['y']) }
                        well_origins.append( origin )

                return well_origins


class six_well_biocell_just_corners_scan(six_well_biocell_scan):
        '''6_well_biocell_just_corners_scan(top_left_corner, scan_id=None, num_h_scan_points=1, num_v_scan_points=1, verbose=False,
                       clip_duration=3, video_format_params=None)

        Modified version of 6_well_scan that includes only the four corners of
        each well instead of a full scan. It is simplified this way in order to
        verify the lateral location of the wells by visualizing the corners.

        top_left_origin:        Bottom-left corner of the top-left well in the format
                                {'x':<>, 'y':<>}
                                
        scan_id:                User-defined string identifier of the scan

        num_h_scan_points:      Number of scan points across each well (if we
                                were doing a full scan)

        num_v_scan_points:      Number of scan points down each well (if we were
                                doing a full scan)
        
        clip_duration:          Duration in seconds to record video for each scan point

        video_format_params:    Dictionary of video params to be passed to camera when
                                recording video clips

        verbose:                Verbosity

        Assumes that the orientation of the plate is such that it is vertical
        (long axis of plate and wells is in y-direction) and the top-left well is
        higher than the top-right well.
        '''


        def __init__(self,
                     top_left_origin,
                     scan_id = None,
                     num_h_scan_points = 1,
                     num_v_scan_points = 1,
                     clip_duration = 3,
                     video_format_params = None,
                     verbose = False):


                self.calibrated_for_z = False

                scan_base.__init__(self, scan_id, video_format_params)

                well_origins = self.generate_well_origins( top_left_origin )

                scan_base.build_scan_from_target_origins(self,
                                                         well_origins,
                                                         target_width = 19.1,
                                                         target_height = 26.8,
                                                         num_h_scan_points = num_h_scan_points,
                                                         num_v_scan_points = num_v_scan_points,
                                                         just_corners = True,
                                                         verbose = verbose )

                for scanpoint in self.scanpoints:
                        scanpoint['t'] = clip_duration


def xtz2xyz(xtz, arm_length = 55.0):
        '''xthetaz2xyz( xtz, arm_length = 55.0 )

        Convert a {'X':<>, 'theta':<> } point to a { 'x':<> 'y':<>} point
        If the passed dict has z0, z1, and/or t keys, the values are copied over
        '''
        
        xyz = {}
        xyz['x'] = xtz['X'] - math.sin( math.radians(xtz['theta']) ) * arm_length
        xyz['y'] = -math.cos( math.radians(xtz['theta']) ) * arm_length

        # TODO: make generic for non x,y,theta keys
        if xtz.has_key('z0'):
                xyz['z0'] = xtz['z0']
        if xtz.has_key('z1'):
                xyz['z1'] = xtz['z1']
        if xtz.has_key('t'):
                xyz['t'] = xtz['t']

        return xyz

                

################################################################################



class scancam_base():
        '''scancam_base(stages, camera, scancam_id = None, camera_warmup = 0.0, stage_timeout = 100)

        Base class for scacncams.

        stages:         Dictionary of zaber_devices that comprise the scancam.
                        The keys are the axis identifiers. (e.g. 'X', 'theta',
                        'z')

        camera:         Camera class derived from camera_base
        
        scancam_id:     Identifier string for class

        camera_warmup:  Seconds that it takes to warm up camera. Used to calculate second
                        depth move speed so that the move fudges closer to the clip duration

        stage_timeout:  Number of seconds to wait for stage moves before timing out.
        '''


        def __init__(self, stages, camera, scancam_id = None, camera_warmup = 0.0, stage_timeout = 100):

                self.stages = stages
                self.camera = camera
                if scancam_id == None:
                        scancam_id = str(hash(self))
                self.id = scancam_id
                self.camera_warmup = camera_warmup
                self.stage_timeout = stage_timeout

        def get_id(self):
                '''get_id()

                Returns identifier string for this scancam instance. If none was
                given during construction, it defaults to a hash of the object
                at that time.
                '''
                return self.id


        def wait_for_stages_to_complete_actions(self):
                '''scancam_base.wait_for_stages_to_complete_actions()

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
                        for stage in self.stages.values():
                                #stage.stop()
                                pass
                        raise


        def build_timestring(self, t):
                '''scancam_base.build_timestring(time)

                Build timestring in the format:
                        YYYY-MM-DD_HH-MM-SS

                t:   Time value in seconds past the epoch
                '''
                return "%04d-%02d-%02d_%02d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)

                
        def stop(self):
                '''scancam_base.stop()

                Send stop command to all stages.
                '''
                for stage in self.stages.values():
                        stage.stop()


        def home(self):
                '''scancam_base.home()

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
                '''scancam_base.move_stages(stage_targets, wait_for_move_to_complete = True)

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
                '''scancam_base.in_action()

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

                        # TODO: set speed x_stage.set_target_speed_in_units( 6.0 )
                        
                        move_setting = {'x': point['x'],
                                        'y': point['y']}
                        if point.has_key('z0'):
                                # Set z-axis speed to standard moderately fast value. It may have been set to a
                                # different value during an image-through-depth sequence
                                # TODO: fix this to work more appropriately for class
                                z_stage.set_target_speed_in_units( STANDARD_Z_SPEED, 'A-series' )

                                move_setting['z'] = point['z0']

                        # Move to x,y,z
                        self.move( move_setting )
                        

                        # If this scan point has no time value, there is no video to record
                        # Probably a transitional point that is just there to avoid crashing
                        # into walls.
                        if not point.has_key('t'):
                                log.info("Point has no time value. Skipping z1 and video")
                                continue
                        
                        clip_duration = int(point['t'])
                        
                        # If there is a second z-axis value, start the move to it as we start the video clip
                        # The clip will progress through the depth of the move. If t = 0 it is for an image so skip z1
                        if point.has_key('z1') and clip_duration != 0:
                                # The move from z0 to z1 should take the same amount of time as the video clip duration
                                # But, the camera may require a little warm-up time from system call to the first frame
                                # We'll add a small buffer of time to the z-axis move so that even if the move and clip
                                # don't start together, at least they will end together.
                                target_z_speed = abs(point['z1']-point['z0']) / (float(point['t']) + self.camera_warmup)

                                if target_z_speed > MAX_Z_MOVE_SPEED:
                                        # Calculate clip duration, rounding up to next int
                                        clip_duration = ceil(abs(point['z1']-point['z0']) / MAX_Z_MOVE_SPEED - self.camera_warmup)
                                        log.warning( str(target_z_speed) + " is too fast. Setting to max speed: " + str(MAX_Z_MOVE_SPEED) + \
                                                              " And extending clip duration to: " + str(clip_duration))
                                        target_z_speed = MAX_Z_MOVE_SPEED
                                # TODO: fix set_target_speed_in_units call to be type agnostic
                                # TODO: change to be more scancam class appropriate
                                z_stage.set_target_speed_in_units( target_z_speed, 'A-series' )

                                move_setting = {'z': point['z1']}
                                scancam.move( move_setting, wait_for_completion = False )
                      
                        # Build video file target basename in the format:
                        #       <payload>_<scan definition ID>_<scan point ID>.<YYYY-MM-DD_HH-mm-SS>.h264
                        t_str = self.build_timestring( gmtime(time()) )
                        # TODO: use host and scan id for beginning of base
                        if point.has_key('point-id'):
                                filename_base = "proto_built-in-scan_" + point['point-id'] + '.' + t_str
                        else:
                                filename_base = "proto_built-in-scan_" + str(scan_point_num) + '.' + t_str

                        # Record Video                        
                        try:
                                camera.record_video(filename_base, clip_duration, xyz_scan.video_format_params)
                        except KeyboardInterrupt:
                                raise        
                        except:
                                raise

                        # Assure that the last z-axis move was completed
                        try:
                                scancam.wait_for_stages_to_complete_actions()
                        except zaber_device.DeviceTimeoutError, device_id:
                                log.warning("Device %d timed out during second z move on scan point %d" % (device_id, scan_point_num))
                                raise

class xthetaz_scancam(scancam_base):
        '''xthetaz_scancam(self, stages, arm_length = 52.5, min_X = 0.0, max_X = 176.0, camera_warmup = 0.0, stage_timeout = 100)

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

        def __init__(self, stages, camera, arm_length = 52.5, min_X = 0.0, max_X = 176.0, camera_warmup = 0.0, stage_timeout = 100):

                self.arm_length = arm_length
                self.min_X = min_X
                self.max_X = max_X

                # TODO: Import hardware id to stage id mapping and use to build stage dict
                xtz_stages = {}
                xtz_stages['X'] = stages[0]
                xtz_stages['theta'] = stages[1]
                #xtz_stages['z'] = stages[2]

                scancam_base.__init__(self, xtz_stages, camera, camera_warmup = camera_warmup, stage_timeout = stage_timeout)

                self.used_negative_of_angle_last_time = False                


        def xy2xtheta(self, xy_point):
                '''xthetaz_scancam.xy2xtheta(xy_point)

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
                '''xthetaz_scancam.move(settings)

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

                        
                        
#####################################################################################################################

                  

if __name__ == '__main__':

        # parse arguments
        # scancam [OPTION]... [SCANFILE]...
        #
        # -p, --minimum-period in minutes
        args = parse_arguments(sys.argv)

        # Log all variables handled by config file and command line args
        log.info("Variables handled by config file and command line args:")
        arg_dict = vars(args)
        for arg in arg_dict:
                log.info("    " + arg + ": " + str(arg_dict[arg]))

        # open file and unpickle the scan
        scan_list = pickle.load(args.scanfile)
        args.scanfile.close()

        # List scan(s) at startup
        # scan is scan class containing a list of scanpoints represented as dictionaries with the keys:
        #	x	x-axis target location in mm
        #	theta	rotary stage target location in deg
        #	z	z-axis target location in mm
        #	t	time in seconds to record video
        for scan in scan_list:
                scan.log_scan_contents( log, logging.INFO )        

        # Put everything in try statement so that we can finally close the serial port on any error
        completed_scan_sets = 0
        try:
                # Create serial connection
                try:
                        ser = serial_connection(args.serial_dev)
                except serial.SerialException, errmsg:
                        log.critical("Error constructing serial connection: " + errmsg)
                        log.critical("If we don't have a serial connection, we're dead in the water. Exiting.")
                        sys.exit(1)
                        
                # TODO Flush serial port and anything else necessary to have clean comm start

                # Derive verbosity for stages from log level
                if args.log_level == 'DEBUG':
                        verbose = True
                else:
                        verbose = False

                # Instantiate the axes
                # From T-LSM200A specs: mm_per_rev = .047625 um/microstep * 64 microstep/step * 200 steps/rev * .001 mm/um = .6096 mm/rev
                x_stage = linear_slide(ser, 1, mm_per_rev = .6096, verbose = verbose, run_mode = STEP)

                # From T-RS60A specs: .000234375 deg/microstep * 64 microsteps/step = .015 deg/step
                theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = verbose, run_mode = STEP)

                # From LSA10A-T4 specs: mm_per_rev = .3048 mm/rev
                #z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = verbose, run_mode = STEP)

                camera = ueye_camera( cam_id = 1, log_level = log.getEffectiveLevel() ) 

                scancam = xthetaz_scancam( [ x_stage, theta_stage ], 
                                           camera, 
                                           stage_timeout = args.stage_timeout,
                                           camera_warmup = args.camera_warmup )

                # Open serial connection. This starts the queue handler
                log.debug("Opening serial connection in thread")
                thread.start_new_thread( ser.open, ())

                # TODO: Send command to reset stages to defaults
                # TODO: Read in the default target speed for z so we can use it for z0 moves

                if args.home_on_start:
                        scancam.home()
                                                        
                # Loop and continually scan with a timed periodicity
                last_scan_start_time = 0
                while (1):

                        # Once a second, check to see if it's time to start a new scan
                        if time() < last_scan_start_time + args.period*60.0:
                                sleep(1)
                                continue
                        # TODO: Handle start time of scans that error out
                        last_scan_start_time = time()
                        
                               
                        # Walk through scans
                        log.debug("Starting scan set number" + str(completed_scan_sets + 1))
                        for scan in scan_list:
                                scancam.scan_action(scan)
  
                        completed_scan_sets += 1

                        if not args.continuous and completed_scans == args.num_scans:
                                break
                        
        except KeyboardInterrupt:
                 log.debug("Completed %d scan sets." % completed_scan_sets)


        finally:
                # Send stop command to all devices
                try:
                        scancam
                        scancam.stop()
                except NameError:
                        # If the scancam has not been intitialized, don't stop it
                        pass
                
                # Close serial connection before final exit
                log.info("Closing serial connection")
                ser.close()
                log.info("Connection closed")

