import math




#
# Each scan is a sequential list of dictionaries, each of which represents a single
# scan point. Each point must minimally include 'x' and 'y' or 'X' and 'theta' keys.
#
# In order to differentiate between the cartesian and specialized rotary coordinates
# a lower case 'x' is used for cartesian and an uppercase 'X' for the rotary.
#
# The scans are generally first created in standard cartesian coordinates (x, y)
# for familiarity and ease, but the ScanCam is implemented with a rotary axis so they
# must be transformed into X-theta coordinates before commanding the devices.
#
# The dictionaries may optionally also include the following keys:
#   'z0' -      The depth setting for a given scan point. When used with 'z1', the
#               camera can also be used to record video while walking through the
#               depth of a culture. In these cases, the scan will alternate walking
#               from z0 to z1 and from z1 to z0.
#   'z1' -      The second depth setting when imaging through the culture depth
#   't'  -      Time duration in seconds of the video clip at a given point. Also used
#               to adjust the speed of the z-move during imaging through the culture
#               depth to match the z move to cooincide with the video duration.
#   'point-id'- User-defined identifier for the point. Defaults to sequential integers
#               for most scan builders.
#               
#
# There are three types of time values for a scan point.
#       no 't' key:     Skip z1 move and all video calls. This may be used for intermediate
#                       scan points that don't require video
#       t = 0:          Place-holder for taking an image instead of video.
#       t > 0:          Video clip duration. Also used to determine z-speed during move to z1
#



verbose_for_coord_trans = False
verbose_for_scan_build = False



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

                
def xyz_scan_2_xthetaz_scan ( xyz_scan, arm_length = 52.5, min_X = 0.0, max_X = 176.0, verbosity = 0 ):
        '''
        xyz2xtz ( xyz_scan, arm_length, min_X, max_X )

        Use physical geometry to translate from a cartesian xyz coord scan to the one
        described by the x, theta, z where theta is the angle of the rotary axis
        '''
        
        xthetaz_scan = []
        used_negative_last_time = False
        for xyz in xyz_scan:
                x = xyz['x']
                y = xyz['y']

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
                if not used_negative_last_time:
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
                        used_negative_last_time = not used_negative_last_time
                        theta = 360 - theta     
                        X = x - arm_length * math.sin( math.radians( theta ) )

                # If X is still out of bounds, it must be unachievable. Raise exception
                if X < min_X or X > max_X:
                        print "Unable to translate (%f, %f) to X-theta coordinates." % (x,y)
                        print "Calculated X value of %f is out of range." % X
                        raise SyntaxError
                
                # Put x-theta coord in scan list
                # TODO: make generic for non x,y,theta 
                xtz = { 'X': X, 'theta': theta }
                if xyz.has_key('z0'):
                        xyz['z0'] = xyz['z0']
                if xyz.has_key('z1'):
                        xtz['z1'] = xyz['z1']   
                if xyz.has_key('t'):
                        xtz['t'] = xyz['t']
                if xyz.has_key('point-id'):
                        xtz['point-id'] = xyz['point-id']
                xthetaz_scan.append( xtz )
                if verbosity: print "Converted to", xtz, "from", xyz 

        return xthetaz_scan




def build_xyz_scan_from_target_corners( corners, target_width = 19.1, target_height = 26.8,
                                        num_h_scan_points = 4, num_v_scan_points = 5, just_corners = False, verbosity = 0):
        '''build_xyz_scan_from_target_corners( corners, target_width = 19.1, target_height = 26.8,
                        num_h_scan_points = 4, num_v_scan_points = 5, just_corners = False, verbosity = 0)
        Builds an xyz scan of points across a list of equally sized rectangular targets.

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
        xyz_scan = []
        first_z_last_time = ''
        corner_num = 0
        for corner in corners:
                corner_num += 1
                # The center of the first cell isn't the corner, it's half a cell over (and down)
                x0 = corner['x'] - cell_width/2.0
                y0 = corner['y'] - cell_height/2.0
                for jj in range(num_v_scan_points):
                        for ii in range(num_h_scan_points):
                                xyz = {}
                                
                                # It is useful for location calibration to be able to find the corners of the
                                # wells. So with a True just_corners value we adjust the algorithm to skip all
                                # locations except the corners.
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
                                        xyz['x'] = x0 - i*cell_width
                                if j%2 == 1:
                                        xyz['x'] = x0 - (num_h_scan_points-1-i)*cell_width

                                xyz['y'] = y0 - j*cell_height

                                # If there is a second z-axis value, alternate which one you
                                # start with to avoid waiting for z to get back to z0 every time
                                if corner.has_key('z1'):
                                        if first_z_last_time != 'z0':
                                                xyz['z0'] = corner['z0']
                                                xyz['z1'] = corner['z1']
                                                first_z_last_time = 'z0'
                                        else:
                                                xyz['z0'] = corner['z1']
                                                xyz['z1'] = corner['z0']
                                                first_z_last_time = 'z1'
                                # If there's no second z value, just use the one you have
                                else:
                                        if xyz.has_key('z0'):
                                                xyz['z0'] = corner['z0']
                                                
                                if corner.has_key('t'):
                                        xyz['t'] = corner['t']

                                # Add cell identifier
                                xyz['point-id'] = "%d-%d-%d" % ( corner_num, j+1, i+1)
                                
                                # We're done with that point, add it to the new scan
                                xyz_scan.append( xyz )
                                if verbosity: print "Appended", xyz

        return xyz_scan




def generate_six_well_xy_corners( top_left_corner ):
        '''generate_six_well_xy_corners( top_left_corner_of_top_left_well )

        Takes the top-left corner of the top-left well and generates a list
        of the top-left corners of all six wells.

        The x-y values in this list can be used (with z and t values added)
        to generate a set of corners that generate a full scan
        with build_xyz_scan_from_target_corners()

        Takes a dictionary with two keys: 'x' and 'y'
        '''

        # These were calculated from the list of twelve well corners measured from the SolidWorks model
        delta_corners = [       {'y': 0.0, 'x': 0.0},
                                {'y': 38.3, 'x': 0.0},
                                {'y': 76.6, 'x': 0.0},
                                {'y': 8.7, 'x': 28.1},
                                {'y': 47.0, 'x': 28.1},
                                {'y': 85.3, 'x': 28.1}    ]

        corners = []
        for delta_corner in delta_corners:
                corner = {'x': (top_left_corner['x']-delta_corner['x']), 'y': (top_left_corner['y']-delta_corner['y']) }
                corners.append( corner )

        return corners



# Temporary x--theta scan for testing
xtz_keys = ( 'X', 'theta', 'z', 't' )
arb_test_xtz_scan = [ dict( zip(xtz_keys, ( 20, 45, 1, 0 ))) ]
arb_test_xtz_scan += [ dict( zip(xtz_keys, ( 40, 90, 4, 0 ))) ]
arb_test_xtz_scan += [ dict( zip(xtz_keys, ( 5, 120, 7, 0 ))) ]



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
model_xyz_scan = build_xyz_scan_from_target_corners( corners_from_sw )


          


# Heuristically found culture geometry on prototype
# generate scan from calculated corner
proto_home = {'x':69.0, 'y':56.0 }
proto_corners = generate_six_well_xy_corners( proto_home )
for corner in proto_corners:
        #corner['z0'] = 2.0
        #corner['z1'] = 5.0
        corner['t'] = 10
        #pass
proto_xyz_scan = build_xyz_scan_from_target_corners( proto_corners,
                                                     num_h_scan_points = 3,
                                                     num_v_scan_points = 4,
                                                     #just_corners = True,
                                                     verbosity = verbose_for_scan_build )

