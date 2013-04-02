import math






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

