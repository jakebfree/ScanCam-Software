import pickle
import scancam


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



# Heuristically found culture geometry on prototype
# generate scan from calculated corner
module1 = scancam.SixWellBioCellJustCornersScan( {'x':152.2, 'y':29.2 },
                          scan_id = 'module1',
                          num_h_scan_points = 3,
                          num_v_scan_points = 4,
                          video_format_params = { 'subsampling': 3,
                                           'cropping': (320, 2240, 0, 1920) },
                          verbose = True )

module2 = scancam.SixWellBioCellJustCornersScan( {'x':28.1, 'y':29.2 },
                          scan_id = 'module2',
                          num_h_scan_points = 3,
                          num_v_scan_points = 4,
                          video_format_params = { 'subsampling': 3,
                                           'cropping': (320, 2240, 0, 1920) },
                          verbose = True )

scanfile = open("flight.scan", 'wb')

pickle.dump( [module1, module2], scanfile)

scanfile.close()
