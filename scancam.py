import argparse, sys
from time import sleep, time, gmtime
import thread
import pickle
import math
import os
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






DEFAULT_STAGE_ACTION_TIMEOUT = 60       # seconds
MAX_CLIP_LENGTH = 60                    # seconds
MAX_Z_MOVE_SPEED = 3.0                  # mm/second
CAMERA_STARTUP_TIME = 0.0               # seconds

min_period_bt_scans = 1                 # in minutes
verbose = True
home_on_start = False
just_one_scan = True
skip_video = True
comm_device = "COM3"
scan_filename = "/etc/"

video_location = "/home/freemajb/data/scancam_proto_videos/"







verbose_for_scan_build = True



class scan_base():
        '''scan_base(id)

        Implements the scan base class.

        id: A user-defined string for this scan. If no id is passed then a
                string representation of the hash of this instance is used
                
        Each scan is a sequential list of dictionaries, each of which represents a single
        scan point. Each point must minimally include 'x' and 'y' or 'X' and 'theta' keys.

        In order to differentiate between the cartesian and specialized rotary coordinates
        a lower case 'x' is used for cartesian and an uppercase 'X' for the rotary.

        The scans are generally first created in standard cartesian coordinates (x, y)
        for familiarity and ease, but the ScanCam is implemented with a rotary axis so they
        must be transformed into X-theta coordinates before commanding the devices.

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

        def __init__(self, id=None):
                if id == None:
                        id = str(hash(self))
                self.id = id

                self.scanpoints = []



        def build_scan_from_target_corners(self, corners, target_width = 19.1, target_height = 26.8,
                                           num_h_scan_points = 4, num_v_scan_points = 5, just_corners = False,
                                           verbosity = 0):
                '''scan_base.build_xyz_scan_from_target_corners( corners, target_width = 19.1, target_height = 26.8,
                                num_h_scan_points = 4, num_v_scan_points = 5, just_corners = False, verbosity = 0)

                corners:        List of dictionaries each of which represents a corner location in the format:
                                {'x'=<>, 'y'=<>, 'area_id'=<>}

                target_width:   Width (in mm) of the target areas to scan over

                target_height:  Height (in mm) of the target areas to scan over

                num_h_scan_points:  Number of scan points across each target area

                num_v_scan_points:  Number of scan points down each target area

                just_corners:   Boolean that when true creates a scan consisting only of the four
                                corner scan points of each area that would be created given the other
                                args. It may be useful for verifying the x-y calibration of the scan
                                since the edges of the wells are likely to be visible in the camera FOV

                verbosity:      Verbosity
                
                
                Builds an scan of points across a list of equally sized rectangular targets.

                The scan begins in the top-left corner of the first target and scans across and down it
                in an ess pattern that goes to the right across a row and left back across the next row.
                It then jumps to the top-left corner of the next target and scans it. Repeating until
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
                corner_num = 0
                for corner in corners:
                        corner_num += 1
                        # The center of the first cell isn't the corner, it's half a cell over (and down)
                        x0 = corner['x'] - cell_width/2.0
                        y0 = corner['y'] - cell_height/2.0
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

                                        scan_point['y'] = y0 - j*cell_height

                                        # If there is a second z-axis value, alternate which one you
                                        # start with to avoid waiting for z to get back to z0 every time
                                        if corner.has_key('z1'):
                                                if first_z_last_time != 'z0':
                                                        scan_point['z0'] = corner['z0']
                                                        scan_point['z1'] = corner['z1']
                                                        first_z_last_time = 'z0'
                                                else:
                                                        scan_point['z0'] = corner['z1']
                                                        scan_point['z1'] = corner['z0']
                                                        first_z_last_time = 'z1'
                                        # If there's no second z value, just use the one you have
                                        else:
                                                if scan_point.has_key('z0'):
                                                        scan_point['z0'] = corner['z0']
                                                        
                                        if corner.has_key('t'):
                                                scan_point['t'] = corner['t']

                                        # Add cell identifier
                                        scan_point['point-id'] = "%d-%d-%d" % ( corner_num, j+1, i+1)

                                        # Assign target areas id to point. This may be useful later when
                                        # calibrating in cases where a given calibration is to be applied
                                        # to all points in a target area. If none given, serialize.
                                        if corner.has_key('area-id'):
                                                scan_point['area-id'] = corner['area-id']
                                        else:
                                                scan_point['area-id'] = corner_num
                                                
                                        # We're done with that point, add it to the new scan
                                        self.scanpoints.append( scan_point )
                                        if verbosity: print "Appended", scan_point




                
class six_well_scan(scan_base):
        '''6_well_scan(top_left_corner, scan_id=None, num_h_scan_points=1, num_v_scan_points=1,
                        clip_duration = 10, verbosity=False)

        Takes the top-left corner of the top-left well and generates a scan based
        on the known geometry of the 6-well plate measured from the SolidWorks model

        top_left_corner:        Top-left corner of the top-left well in the format
                                {'x':<>, 'y':<>}
                                
        scan_id:                User-defined string identifier of the scan

        num_h_scan_points:      Number of scan points across each well

        num_v_scan_points:      Number of scan points down each well
        
        clip_duration:          Duration in seconds to record video for each scan point

        verbosity:              Verbosity

        Assumes that the orientation of the plate is such that it is vertical
        (long axis of plate and wells is in y-direction) and the top-left well is
        higher than the top-right well.
        '''


        def __init__(self,
                     top_left_corner,
                     scan_id = None,
                     num_h_scan_points = 1,
                     num_v_scan_points = 1,
                     clip_duration = 10,
                     verbosity=False):

                self.calibrated_for_z = False

                # These were calculated from a list of twelve well corners measured from the SolidWorks model
                self.delta_corners = [  {'y': 0.0, 'x': 0.0},
                                        {'y': 38.3, 'x': 0.0},
                                        {'y': 76.6, 'x': 0.0},
                                        {'y': 8.7, 'x': 28.1},
                                        {'y': 47.0, 'x': 28.1},
                                        {'y': 85.3, 'x': 28.1}    ]

                scan_base.__init__(self, scan_id)

                # Build list of top left well corners from top-left corner of top-left well and deltas
                # TODO: make into inheritable function
                well_top_left_corners = []
                for delta_corner in self.delta_corners:
                        corner = {'x': (top_left_corner['x']-delta_corner['x']), 'y': (top_left_corner['y']-delta_corner['y']) }
                        well_top_left_corners.append( corner )


                scan_base.build_scan_from_target_corners(self,
                                                         well_top_left_corners,
                                                         target_width = 19.1,
                                                         target_height = 26.8,
                                                         num_h_scan_points = num_h_scan_points,
                                                         num_v_scan_points = num_v_scan_points,
                                                         verbosity = verbosity )

                for scanpoint in self.scanpoints:
                        scanpoint['t'] = clip_duration




class six_well_just_corners_scan(scan_base):
        '''6_well_scan(top_left_corner, scan_id=None, num_h_scan_points=1, num_v_scan_points=1, verbosity=False)

        Modified version of 6_well_scan that includes only the four corners of
        each well instead of a full scan. It is simplified this way in order to
        verify the lateral location of the wells by visualizing the corners.

        top_left_corner:        Top-left corner of the top-left well in the format
                                {'x':<>, 'y':<>}
                                
        scan_id:                User-defined string identifier of the scan

        num_h_scan_points:      Number of scan points across each well (if we
                                were doing a full scan)

        num_v_scan_points:      Number of scan points down each well (if we were
                                doing a full scan)
        
        clip_duration:          Duration in seconds to record video for each scan point

        verbosity:              Verbosity

        Assumes that the orientation of the plate is such that it is vertical
        (long axis of plate and wells is in y-direction) and the top-left well is
        higher than the top-right well.
        '''


        def __init__(self,
                     top_left_corner,
                     scan_id = None,
                     num_h_scan_points = 1,
                     num_v_scan_points = 1,
                     verbosity=False):

                # Build list of top left well corners from top-left corner of top-left well and deltas
                # TODO: make into function in parent class
                well_top_left_corners = []
                for delta_corner in self.delta_corners:
                        corner = {'x': (top_left_corner['x']-delta_corner['x']), 'y': (top_left_corner['y']-delta_corner['y']) }
                        well_top_left_corners.append( corner )


                scan_base.build_scan_from_target_corners(self,
                                                         well_top_left_corners,
                                                         target_width = 19.1,
                                                         target_height = 26.8,
                                                         num_h_scan_points = num_h_scan_points,
                                                         num_v_scan_points = num_v_scan_points,
                                                         just_corners = True,
                                                         verbosity = verbosity )

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

                



# Place-holding xyz scan matrix for basic testing
# all numbers in mm
xyz_keys = ( 'x', 'y', 'z0', 'z1', 't' )
arb_test_xyz_scan = [ dict( zip(xyz_keys, ( 30, 50, 1, 4, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 40, 40, 6, 0, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 50, 30, 1, 4, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 60, -20, 6, 0, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 70, -10, 1, 4, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 50, -10, 6, 0, 0 ))) ]




# First cut at flight-like scan
# Corners determined from solid model represent top and right edges of wells
corners_from_sw = ( {'x':152.2, 'y':47.3, 'z0':2.0, 'z1':4.0, 't':10},
            {'x':152.2, 'y':9.0, 'z0':0.0, 'z1':6.0, 't':3},
            {'x':152.2, 'y':-29.3, 'z0':1.5, 'z1':4.5, 't':3},
            {'x':124.1, 'y':47.3, 'z0':0.0, 'z1':6.0, 't':3},
            {'x':124.1, 'y':9.0, 'z0':2.0, 'z1':4.0, 't':3},
            {'x':124.1, 'y':-29.3, 'z0':0.0, 'z1':6.0, 't':3},
            {'x':28.1, 'y':47.3, 'z0':0.0, 't':3},
            {'x':28.1, 'y':9.0, 'z0':1.0, 't':3},
            {'x':28.1, 'y':-29.3, 'z0':2.0, 't':3},
            {'x':0.0, 'y':47.3, 'z0':3.0, 't':3},
            {'x':0.0, 'y':9.0, 'z0':4.0, 't':3},
            {'x':0.0, 'y':-29.3, 'z0':5.0, 't':3}
        )
# TODO: Adapt to work with classes
#model_scan = build_xyz_scan_from_target_corners( corners_from_sw )


          


# Heuristically found culture geometry on prototype
# generate scan from calculated corner
proto_scan = six_well_scan( {'x':69.0, 'y':56.0 },
#                          scan_id = 'proto_scan',
                          num_h_scan_points = 1,
                          num_v_scan_points = 1,
                          verbosity = verbose_for_scan_build )


# HACK to set the scan before we import from file
xyz_scan = proto_scan 
#xyz_scan = model_xyz_scan



################################################################################



class scancam_base():
        '''scancam_base(self, stages)

        Base class for scacncams.

        stages:         Dictionary of zaber_devices that comprise the scancam.
                        The keys are the axis identifiers. (e.g. 'X', 'theta',
                        'z')
        '''


        def __init__(self, stages):

                self.stages = stages


        def wait_for_stages_to_complete_actions(self, timeout_secs):
                '''scancam_base.wait_for_stages_to_complete_actions(timeout_secs)

                For each scancam stage, wait until .in_action() returns False
                '''
                # TODO: Fix timing such that if takes first stage X seconds to
                # get to its target then next stage doesn't have a cumulative
                # wait of up to X + timeout_secs
                try:
                        for stage in self.stages.values():
                                stage.wait_for_action_to_complete( timeout_secs )
                except zaber_device.DeviceTimeoutError, stage_id:
                        # If one device times out, stop all of them
                        for stage in self.stages.values():
                                #stage.stop()
                                pass
                        raise


        def build_timestring(self, time):
                '''scancam_base.build_timestring(time)

                Build timestring in the format:
                        YYYY-MM-DD_HH-MM-SS

                time:   Time value in seconds past the epoch
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
                        self.wait_for_stages_to_complete_actions( DEFAULT_STAGE_ACTION_TIMEOUT )
                except zaber_device.DeviceTimeoutError, device_id:
                        print "Device", device_id, "timed out during intial homing"
                        raise


        def move_stages(self, stage_targets):
                '''scancam_base.move_stages(scanpoint, verbosity = False)

                Move as many stages as are specified in the scanpoint and wait
                for completion.

                stage_targets:  Dictionary of stage targets. Keys are the stage
                                ids. Values are the stage targets in scientific
                                units.

                verbosity:      Verbosity
                '''
                for stage_id in stage_targets:
                        # Enqueue scan point move commands
                        self.stages[stage_id].move_absolute( stage_targets[stage_id] )

                for stage_id in stage_targets:
                        # Step to next queued scan point for all axes
                        self.stages[stage_id].step()

                # Wait for all moves to complete
                try:
                        self.wait_for_stages_to_complete_actions( DEFAULT_STAGE_ACTION_TIMEOUT )
                except zaber_device.DeviceTimeoutError, device_id:
                        print "Device", device_id, "timed out during move for scan point", scan_point_num
                        raise


class xthetaz_scancam(scancam_base):
        '''xthetaz_scancam(self, stages, arm_length = 52.5, min_X = 0.0, max_X = 176.0,

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
        '''

        def __init__(self, stages, arm_length = 52.5, min_X = 0.0, max_X = 176.0):

                self.arm_length = arm_length
                self.min_X = min_X
                self.max_X = max_X

                # TODO: Import hardware id to stage id mapping and use to build stage dict
                xtz_stages = {}
                xtz_stages['X'] = stages[0]
                xtz_stages['theta'] = stages[1]
                #xtz_stages['z'] = stages[2]

                scancam_base.__init__(self, xtz_stages)

                self.used_negative_of_angle_last_time = False                


        def xy2xtheta(self, xy_point, verbosity = 0):
                '''xthetaz_scancam.xy2xtheta(xy_point, verbosity = 0)

                Use physical geometry of the scancam to translate from a
                cartesian xy coord point (in mm) to the one implemented by our
                X-theta hardware where X is the X-stage setting in mm and theta
                is the rotary axis setting in degrees.

                xy_point:       Dictionary containing the x and y values for the
                                scan point. Only the 'x' and 'y' keys are used
                                by this functions, but other may be included.

                verbosity:      Verbosity
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
                if not used_negative_of_angle_last_time:
                        try:
                                theta = math.degrees( math.acos( float(-y)/float(arm_length) ))
                        except ValueError:
                                past_reach = True
                else:
                        try:
                                theta = 360 - math.degrees( math.acos( float(-y)/float(arm_length) ))
                        except ValueError:
                                past_reach = True
                
                # If the acos call raised an exception, the desired y-value is beyond the reach
                # of the swing arm. Set the rotary axis straight up or down to do the best you can        
                if past_reach:
                        if( y > 0 ):
                                theta = 180.0
                        else:
                                theta = 0.0
                        if verbosity: print "Incapable of reaching location (%f, %f). Setting theta=%f" % (x, y, theta)

                X = x + arm_length * math.sin( math.radians( theta ) )

                # If the calculated X is out of bounds, swing theta to its negative (which could be back
                # to the natural acos)
                if X < min_X or X > max_X:
                        self.used_negative_of_angle_last_time = not self.used_negative_of_angle_last_time
                        theta = 360 - theta     
                        X = x - arm_length * math.sin( math.radians( theta ) )

                # If X is still out of bounds, it must be unachievable. Raise exception
                # TODO: Switch to user defined exception
                if X < min_X or X > max_X:
                        print "Unable to translate (%f, %f) to X-theta coordinates." % (x,y)
                        print "Calculated X value of %f is out of range." % X
                        raise SyntaxError
                
                # Put x-theta coord in scan list
                x_theta_point = { 'X': X, 'theta': theta }
                if verbosity: print "Converted to", x_theta_point, "from", xy_point 

                return x_theta_point


        def scan_action(self, xyz_scan, verbosity = False):

                scan_point_num = 0
                for point in xyz_scan.scanpoints:

                        scan_point_num += 1
                        if verbose: print "Step", scan_point_num, point

                        # Enqueue scan point move commands
                        # TODO: set speed x_stage.set_target_speed_in_units( 6.0 )
                        # TODO: handle exceptions with coord trans
                        x_theta_point = xy2xtheta(point)
                        x_stage.move_absolute( x_theta_point['X'] )
                        theta_stage.move_absolute( x_theta_point['theta'] )
                        if point.has_key('z0'):
                                z_stage.move_absolute( point['z0'] )

                                # Set z-axis speed to standard moderately fast value. It may have been set to a
                                # different value during an image-through-depth sequence
                                z_stage.set_target_speed_in_units( STANDARD_Z_SPEED, 'A-series' )
                                z_stage.step()

                        # Step to next queued scan point for all axes
                        for stage in self.stages:
                                stage.step()
                        try:
                                self.wait_for_stages_to_complete_actions( DEFAULT_STAGE_ACTION_TIMEOUT )
                        except zaber_device.DeviceTimeoutError, device_id:
                                print "Device", device_id, "timed out during move for scan point", scan_point_num
                                raise

                        # If this scan point has no time value, there is no video to record
                        if not point.has_key('t'):
                                if verbose: print "Point has no time value. Skipping z1 and video"
                                continue
                        
                        clip_duration = int(point['t'])
                        
                        # If there is a second z-axis value, start the move to it as we start the video clip
                        # The clip will progress through the depth of the move. If t = 0 it is for an image so skip z1
                        if point.has_key('z1') and point['t'] != float(0.0):
                                # The move from z0 to z1 should take the same amount of time as the video clip duration
                                # But, the camera may require a little warm-up time from system call to the first frame
                                # We'll add a small buffer of time to the z-axis move so that even if the move and clip
                                # don't start together, at least they will end together.
                                try:
                                        target_z_speed = abs(point['z1']-point['z0']) / (float(point['t'])+CAMERA_STARTUP_TIME)

                                        if target_z_speed > MAX_Z_MOVE_SPEED:
                                                # Calculate clip duration, rounding up to next int
                                                clip_duration = ceil(abs(point['z1']-point['z0']) / MAX_Z_MOVE_SPEED - CAMERA_STARTUP_TIME)
                                                print target_z_speed, "is too fast. Setting to max speed:", MAX_Z_MOVE_SPEED, \
                                                                      "And extending clip duration to:", clip_duration
                                                target_z_speed = MAX_Z_MOVE_SPEED
                                        # TODO: fix set_target_speed_in_units call to be type agnostic
                                        z_stage.set_target_speed_in_units( target_z_speed, 'A-series' )

                                        z_stage.move_absolute( point['z1'] )
                                        z_stage.step()
                                except ZeroDivisionError:
                                        print "Error: cannot have move from z0 to z1 in 0 seconds. Skipping z1"
                        
                        # TODO: Looks like binned cropping is in terms of binned coordinates, but 
                        # subsampled cropping is in terms of full sensor location (not subsampled) locations
                        # verify and handle appropriately
                        
                        # Start raw video recording
                        camera_id = 1
                        subsampling = 3
                        binning = 0
                        x0 = 320
                        x1 = 2240
                        y0 = 0
                        y1 = 1920

                        # Build video file target basename in the format:
                        #       <payload>_<scan definition ID>_<scan point ID>.<YYYY-MM-DD_HH-mm-SS>.h264
                        t_str = self.build_timestring( gmtime(time()) )
                        if point.has_key('point-id'):
                                filename_base = "proto_built-in-scan_" + point['point-id'] + '.' + t_str
                        else:
                                filename_base = "proto_built-in-scan_" + str(scan_point_num) + '.' + t_str

                        # Build camera command
                        command = "idscam video --id " + str(camera_id)
                        
                        if subsampling:
                                command += " -s " + str(subsampling)
                        if binning:
                                command += " -b " + str(binning)
                        command += " -d " + str(clip_duration)
                        command += " -x0 %d -ex0 %d -x1 %d -ex1 %d -y0 %d -ey0 %d -y1 %d -ey1 %d" % (x0,x0,x1,x1,y0,y0,y1,y1)
                        command += " " + filename_base

                        if verbose: 
                                print "Camera command:", command

                        if skip_video:
                                print "Skipping video. Sleeping", clip_duration, "instead"
                                sleep(clip_duration)
                                continue
                        
                       # System call to camera
                        try:
                                if verbose: print "System call to camera."
                                os.system(command)
                        except KeyboardInterrupt:
                                raise        
                        except:
                                raise

                        # Create video clip from raw frames, -c arg specs clean up of raw files
                        if verbose: print "Starting video compression."
                        comp_command = "raw2h264 -c " + filename_base

                        try:
                                ret_val = os.system( comp_command )
                        except:
                                raise
                        if verbose: print "Return val from compression was", ret_val

                        # Assure that the last z-axis move was completed
                        try:
                                z_stage.wait_for_action_to_complete( DEFAULT_STAGE_ACTION_TIMEOUT )
                        except zaber_device.DeviceTimeoutError, device_id:
                                print "Device", device_id, "timed out during second z move on scan point", scan_point_num
                                raise



# Temporary x--theta scan for testing
xtz_keys = ( 'X', 'theta', 'z', 't' )
arb_test_xtz_scan = [ dict( zip(xtz_keys, ( 20, 45, 1, 0 ))) ]
arb_test_xtz_scan += [ dict( zip(xtz_keys, ( 40, 90, 4, 0 ))) ]
arb_test_xtz_scan += [ dict( zip(xtz_keys, ( 5, 120, 7, 0 ))) ]




if __name__ == '__main__':

        # open file and unpickle the scan

        # parse arguments
        # scancam [OPTION]... [SCANFILE]...
        #
        # -p, --minimum-period in minutes



        # scan is a list of scanpoints represented as dictionaries with the keys:
        #	x	x-axis target location in mm
        #	theta	rotary stage target location in deg
        #	z	z-axis target location in mm
        #	t	time in seconds to record video



        # Create serial connection
        # TODO: handle exceptions
        ser = serial_connection(comm_device)

        # TODO Flush serial port and anything else necessary to have clean comm start


        # Instantiate the axes
        # From T-LSM200A specs: mm_per_rev = .047625 um/microstep * 64 microstep/step * 200 steps/rev * .001 mm/um = .6096 mm/rev
        x_stage = linear_slide(ser, 1, mm_per_rev = .6096, verbose = verbose, run_mode = STEP)

        # From T-RS60A specs: .000234375 deg/microstep * 64 microsteps/step = .015 deg/step
        theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = verbose, run_mode = STEP)

        # From LSA10A-T4 specs: mm_per_rev = .3048 mm/rev
        #z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = verbose, run_mode = STEP)

        scancam = xthetaz_scancam([ x_stage, theta_stage ])

        # Put everything in try statement so that we can finally close the serial port on any error
        try:
                # Open serial connection
                print "Opening serial connection in thread"
                thread.start_new_thread( ser.open, ())


                # TODO: Send command to reset stages to defaults
                # TODO: Read in the default target speed for z so we can use it for z0 moves

                if home_on_start:
                        scancam.home()
                                                        
                # Loop and continually scan with a timed periodicity
                completed_scans = 0
                last_scan_start_time = 0
                while (1):

                        # Once a second, check to see if it's time to start a new scan
                        if time() <= last_scan_start_time + min_period_bt_scans*60.0:
                                sleep(1)
                                continue
                        # TODO: Handle start time of scans that error out
                        last_scan_start_time = time()
                        
                               
                        # Walk through scan
                        if verbose: print "Starting scan number", completed_scans + 1
                        scancam.scan_action(xyz_scan, verbosity=verbose)
  
                        completed_scans += 1

                        if( just_one_scan == True ):
                                break
                        
        except KeyboardInterrupt:
                print "Completed", completed_scans, "scans."


        finally:
                # Send stop command to all devices
                scancam.stop()
                
                # Close serial connection before final exit
                print "Closing serial connection"
                ser.close()
                print "Connection closed"

