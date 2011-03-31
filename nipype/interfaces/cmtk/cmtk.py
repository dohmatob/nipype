from nipype.interfaces.base import BaseInterface, BaseInterfaceInputSpec, traits, File, TraitedSpec, Directory
from nipype.utils.filemanip import split_filename
import re
from glob import glob
from nibabel import load
from nipype.utils.filemanip import fname_presuffix, split_filename, copyfile
import pickle
import scipy as sp
import scipy.io as sio
import os, os.path as op
from time import time
from glob import glob
import numpy as np
import nibabel as nb
import networkx as nx
from nipype.utils.misc import isdefined
import sys

def length(xyz, along=False):
    """
    Euclidean length of track line

    Parameters
    ----------
    xyz : array-like shape (N,3)
       array representing x,y,z of N points in a track
    along : bool, optional
       If True, return array giving cumulative length along track,
       otherwise (default) return scalar giving total length.

    Returns
    -------
    L : scalar or array shape (N-1,)
       scalar in case of `along` == False, giving total length, array if
       `along` == True, giving cumulative lengths.

    Examples
    --------
    >>> xyz = np.array([[1,1,1],[2,3,4],[0,0,0]])
    >>> expected_lens = np.sqrt([1+2**2+3**2, 2**2+3**2+4**2])
    >>> length(xyz) == expected_lens.sum()
    True
    >>> len_along = length(xyz, along=True)
    >>> np.allclose(len_along, expected_lens.cumsum())
    True
    >>> length([])
    0
    >>> length([[1, 2, 3]])
    0
    >>> length([], along=True)
    array([0])
    """
    xyz = np.asarray(xyz)
    if xyz.shape[0] < 2:
        if along:
            return np.array([0])
        return 0
    dists = np.sqrt((np.diff(xyz, axis=0)**2).sum(axis=1))
    if along:
        return np.cumsum(dists)
    return np.sum(dists)

def create_endpoints_array(fib, voxelSize):
    """
    Create the endpoints arrays for each fiber
    Parameters
    ----------
    fib: the fibers data
    voxelSize: 3-tuple containing the voxel size of the ROI image
    Returns
    -------
    (endpoints: matrix of size [#fibers, 2, 3] containing for each fiber the
    index of its first and last point in the voxelSize volume
    endpointsmm) : endpoints in milimeter coordinates
    """

    #print 'Creating endpoint array'
    # Init
    n = len(fib)
    endpoints = np.zeros( (n, 2, 3) )
    endpointsmm = np.zeros( (n, 2, 3) )
    pc = -1

    # Computation for each fiber
    for i, fi in enumerate(fib):

        # Percent counter
        pcN = int(round( float(100*i)/n ))
        if pcN > pc and pcN%1 == 0:
            pc = pcN

        f = fi[0]

        # store startpoint
        endpoints[i,0,:] = f[0,:]
        # store endpoint
        endpoints[i,1,:] = f[-1,:]

        # store startpoint
        endpointsmm[i,0,:] = f[0,:]
        # store endpoint
        endpointsmm[i,1,:] = f[-1,:]

        # Translate from mm to index
        endpoints[i,0,0] = int( endpoints[i,0,0] / float(voxelSize[0]))
        endpoints[i,0,1] = int( endpoints[i,0,1] / float(voxelSize[1]))
        endpoints[i,0,2] = int( endpoints[i,0,2] / float(voxelSize[2]))
        endpoints[i,1,0] = int( endpoints[i,1,0] / float(voxelSize[0]))
        endpoints[i,1,1] = int( endpoints[i,1,1] / float(voxelSize[1]))
        endpoints[i,1,2] = int( endpoints[i,1,2] / float(voxelSize[2]))

    # Return the matrices
    print 'Returning the endpoint matrix'
    return (endpoints, endpointsmm)


def save_fibers(oldhdr, oldfib, fname, indices):
    """ Stores a new trackvis file fname using only given indices """

    #print 'Saving fibers'
    hdrnew = oldhdr.copy()

    outstreams = []
    for i in indices:
        outstreams.append( oldfib[i] )

    n_fib_out = len(outstreams)
    hdrnew['n_count'] = n_fib_out

    nb.trackvis.write(fname, outstreams, hdrnew)


def cmat(track_file, roi_file, dict_file, resolution_network_file, matrix_name, matrix_mat_name):
    """ Create the connection matrix for each resolution using fibers and ROIs. """
    import sys
    import pickle
    import numpy as np
    import nibabel as nb

    print 'Running cmat function'
    filename = track_file
    # create the endpoints for each fibers
    en_fname = op.join(filename, 'endpoints.npy')
    en_fnamemm = op.join(filename, 'endpointsmm.npy')
    ep_fname = op.join(filename, 'lengths.npy')
    curv_fname = op.join(filename, 'meancurvature.npy')
    ##intrk = op.join(gconf.get_cmp_fibers(), 'streamline_filtered.trk')
    intrk = track_file
    print 'Reading Trackvis file {trk}'.format(trk=intrk)
    fib, hdr = nb.trackvis.read(intrk, False)

    # Previously, load_endpoints_from_trk() used the voxel size stored
    # in the track hdr to transform the endpoints to ROI voxel space.
    # This only works if the ROI voxel size is the same as the DSI/DTI
    # voxel size. In the case of DTI, it is not.
    # We do, however, assume that all of the ROI images have the same
    # voxel size, so this code just loads the first one to determine
    # what it should be
    #print 'Loading ROI file {roi}'.format(roi=roi_file)
    firstROIFile = roi_file
    firstROI = nb.load(firstROIFile)
    #print 'First ROI loaded'
    roiVoxelSize = firstROI.get_header().get_zooms()
    (endpoints,endpointsmm) = create_endpoints_array(fib, roiVoxelSize)
    #print 'Saving arrays'
    #np.save(en_fname, endpoints)
    #np.save(en_fnamemm, endpointsmm)
    #print 'Numpy arrays saved'

    n = len(fib)
    print 'Number of fibers {num}'.format(num=n)

    #Load Pickled label dictionary
    file = open(dict_file, "r")
    labelDict = pickle.load(file)
    file.close()
    #print labelDict
    #resolution = gconf.parcellation.keys()
#    resolution = labelDict.keys()

    # create empty fiber label array
    fiberlabels = np.zeros( (n, 2) )
    final_fiberlabels = []
    final_fibers_idx = []

    # Open the corresponding ROI
    roi_fname = roi_file
    roi = nb.load(roi_fname)
    roiData = roi.get_data()

    # Create the matrix
    nROIs = len(labelDict.keys())
    print nROIs
    G = nx.Graph()

    # add node information from parcellation
    if isdefined(resolution_network_file):
        gp = nx.read_graphml(resolution_network_file)
        for u,d in gp.nodes_iter(data=True):
            G.add_node(int(u), d)

    dis = 0

    for i in range(endpoints.shape[0]):

        # ROI start => ROI end
        try:
            startROI = int(roiData[endpoints[i, 0, 0], endpoints[i, 0, 1], endpoints[i, 0, 2]])
            endROI = int(roiData[endpoints[i, 1, 0], endpoints[i, 1, 1], endpoints[i, 1, 2]])
        except IndexError:
            sys.stderr.write("AN INDEXERROR EXCEPTION OCCURED FOR FIBER %s. PLEASE CHECK ENDPOINT GENERATION" % i)
            continue

        # Filter
        if startROI == 0 or endROI == 0:
            dis += 1
            fiberlabels[i,0] = -1
            continue

        if startROI > nROIs or endROI > nROIs:
            sys.stderr.write("Start or endpoint of fiber terminate in a voxel which is labeled higher")
            sys.stderr.write("than is expected by the parcellation node information.")
            sys.stderr.write("Start ROI: %i, End ROI: %i" % (startROI, endROI))
            sys.stderr.write("This needs bugfixing!")
            continue

        # Update fiber label
        # switch the rois in order to enforce startROI < endROI
        #print 'Update fiber label'
        if endROI < startROI:
            tmp = startROI
            startROI = endROI
            endROI = tmp

        fiberlabels[i,0] = startROI
        fiberlabels[i,1] = endROI

        final_fiberlabels.append( [ startROI, endROI ] )
        final_fibers_idx.append(i)


        # Add edge to graph
        # print '# Add edge to graph'
        if G.has_edge(startROI, endROI):
            G.edge[startROI][endROI]['fiblist'].append(i)
        else:
            G.add_edge(startROI, endROI, fiblist = [i])

    #print 'create a final fiber length array'
    # create a final fiber length array
    finalfiberlength = []
    for idx in final_fibers_idx:
        # compute length of fiber
        finalfiberlength.append( length(fib[idx][0]) )

    # convert to array
    print 'convert to array'
    final_fiberlength_array = np.array( finalfiberlength )
    # make final fiber labels as array
    print 'make final fiber labels as array'
    final_fiberlabels_array = np.array(final_fiberlabels, dtype = np.int32)
    # update edges
    # measures to add here
    print 'update edges'

    mlab = np.empty([len(G.nodes())+1,len(G.nodes())+1]) #Plus 1 because of zero indexing
    print 'Matlab matrix shape: {shp}'.format(shp=len(G.nodes())+1)

    for u,v,d in G.edges_iter(data=True):
        G.remove_edge(u,v)
        print [u,v]

        mlab[u][v] = len(d['fiblist'])
        di = { 'number_of_fibers' : len(d['fiblist']), }

        # additional measures
        # compute mean/std of fiber measure
        idx = np.where( (final_fiberlabels_array[:,0] == int(u)) & (final_fiberlabels_array[:,1] == int(v)) )[0]

        di['fiber_length_mean'] = np.mean(final_fiberlength_array[idx])
        di['fiber_length_std'] = np.std(final_fiberlength_array[idx])

        G.add_edge(u,v, di)

    # storing network
    #print '# storing network'
    #print roi_file

    print 'Writing network as {ntwk}'.format(ntwk=matrix_name)
    nx.write_gpickle(G, os.path.abspath(matrix_name))

    mlab_dict = {}
    mlab_dict['cmatrix'] = mlab
    print 'Writing matlab matrix as {mat}'.format(mat=matrix_mat_name)
    sio.savemat(matrix_mat_name,mlab_dict)

class CreateMatrixInputSpec(TraitedSpec):
    roi_file = File(exists=True, mandatory=True, desc='Freesurfer aparc+aseg file')
    dict_file = File(exists=True, mandatory=True, desc='Pickle file containing the label dictionary (see ROIGen)')
    tract_file = File(exists=True, mandatory=True, desc='Trackvis tract file')
    resolution_network_file = File(exists=True, mandatory=True, desc='Parcellation files from Connectome Mapping Toolkit')
    out_matrix_file = File(genfile = True)
    out_matrix_mat_file = File(genfile = True)

class CreateMatrixOutputSpec(TraitedSpec):
    matrix_file = File(desc='NetworkX graph describing the connectivity')
    matrix_mat_file = File(desc='Matlab matrix describing the connectivity')

class CreateMatrix(BaseInterface):
    """
    Performs connectivity mapping and outputs the result as a NetworkX graph and a Matlab matrix

    Example:

    import nipype.interfaces.cmtk.cmtk as ck
    conmap = ck.CreateMatrix()
    conmap.roi_file = 'fsLUT_aparc+aseg.nii'
    conmap.dict_file = 'fsLUT_aparc+aseg.pck'
    conmap.tract_file = 'fibers.trk'
    conmap.run()

    """

    input_spec = CreateMatrixInputSpec
    output_spec = CreateMatrixOutputSpec

    def _run_interface(self, runtime):
        if isdefined(self.inputs.out_matrix_file):
            matrix_file = self.inputs.out_matrix_file
        else:
            matrix_file = self._gen_outfilename('gpickle')
        if isdefined(self.inputs.out_matrix_mat_file):
            matrix_mat_file = self.inputs.out_matrix_mat_file
        else:
            matrix_mat_file = self._gen_outfilename('mat')

        cmat(self.inputs.tract_file, self.inputs.roi_file, self.inputs.dict_file, self.inputs.resolution_network_file,
        matrix_file, matrix_mat_file)

        return runtime

    def _list_outputs(self):
        outputs = self.output_spec().get()
        outputs["matrix_file"]=self._gen_outfilename('gpickle')
        outputs["matrix_mat_file"]=self._gen_outfilename('mat')
        return outputs

    def _gen_outfilename(self, ext):
        _, name , _ = split_filename(self.inputs.tract_file)
        return name + "." + ext

class ROIGenInputSpec(BaseInterfaceInputSpec):
    """
    Generates a ROI file for connectivity mapping and a dictionary file containing relevant node information
    """
    aparc_aseg_file = File(exists=True, mandatory=True, desc='Freesurfer aparc+aseg file')
    LUT_file = File(exists=True, xor=['use_freesurfer_LUT'], desc='Custom lookup table (cf. FreeSurferColorLUT.txt)')
    use_freesurfer_LUT = traits.Bool(xor=['LUT_file'],desc='Boolean value; Set to True to use default Freesurfer LUT, False for custom LUT')
    freesurfer_dir = Directory(requires=['use_freesurfer_LUT'],desc='Freesurfer main directory')
    out_roi_file = File(genfile = True, desc='Region of Interest file for connectivity mapping')
    out_dict_file = File(genfile = True, desc='Label dictionary saved in Pickle format')

class ROIGenOutputSpec(TraitedSpec):
    """
    Generates a ROI file for connectivity mapping and a dictionary file containing relevant node information
    """
    roi_file = File(desc='Region of Interest file for connectivity mapping')
    dict_file = File(desc='Label dictionary saved in Pickle format')

class ROIGen(BaseInterface):
    """
    Generates a ROI file for connectivity mapping and a dictionary file containing relevant node information

    Example:

    import nipype.interfaces.cmtk.cmtk as ck
    ck.ROIGen()
    rg = ck.ROIGen()
    rg.inputs.aparc_aseg_file = 'aparc+aseg.nii'
    rg.inputs.use_freesurfer_LUT = True
    rg.inputs.freesurfer_dir = '/usr/local/freesurfer'
    rg.run()

    The label dictionary is written to disk using Pickle. Resulting data can be loaded using:

    file = open("FreeSurferColorLUT_adapted_aparc+aseg_out.pck", "r")
    file = open("fsLUT_aparc+aseg.pck", "r")
    labelDict = pickle.load(file)

    print labelDict
    """

    input_spec = ROIGenInputSpec
    output_spec = ROIGenOutputSpec

    def _run_interface(self, runtime):
        aparcpath, aparcname, aparcext = split_filename(self.inputs.aparc_aseg_file)
        print 'Using Aparc+Aseg file: {name}'.format(name=aparcname+aparcext)

        if self.inputs.use_freesurfer_LUT:
            self.LUT_file = self.inputs.freesurfer_dir + '/FreeSurferColorLUT.txt'
            print 'Using Freesurfer LUT: {name}'.format(name=self.LUT_file)
            prefix = "fsLUT"
        elif not self.inputs.use_freesurfer_LUT and isdefined(self.inputs.LUT_file):
            self.LUT_file = os.path.abspath(self.inputs.LUT_file)
            lutpath, lutname, lutext = split_filename(self.LUT_file)
            print 'Using Custom LUT file: {name}'.format(name=lutname+lutext)
            prefix = lutname

        self.roi_file = os.path.abspath(prefix + "_" + aparcname + ".nii")
        self.dict_file = os.path.abspath(prefix + "_" + aparcname + ".pck")
        print 'Output names generated'

        if isdefined(self.inputs.out_roi_file):
            self.roi_file = os.path.abspath(self.inputs.out_roi_file)

        if isdefined(self.inputs.out_dict_file):
            self.dict_file = os.path.abspath(self.inputs.out_dict_file)

        MAPPING = [[1,2012],[2,2019],[3,2032],[4,2014],[5,2020],[6,2018],[7,2027],[8,2028],[9,2003],[10,2024],[11,2017],[12,2026],
               [13,2002],[14,2023],[15,2010],[16,2022],[17,2031],[18,2029],[19,2008],[20,2025],[21,2005],[22,2021],[23,2011],
               [24,2013],[25,2007],[26,2016],[27,2006],[28,2033],[29,2009],[30,2015],[31,2001],[32,2030],[33,2034],[34,2035],
               [35,49],[36,50],[37,51],[38,52],[39,58],[40,53],[41,54],[42,1012],[43,1019],[44,1032],[45,1014],[46,1020],[47,1018],
               [48,1027],[49,1028],[50,1003],[51,1024],[52,1017],[53,1026],[54,1002],[55,1023],[56,1010],[57,1022],[58,1031],
               [59,1029],[60,1008],[61,1025],[62,1005],[63,1021],[64,1011],[65,1013],[66,1007],[67,1016],[68,1006],[69,1033],
               [70,1009],[71,1015],[72,1001],[73,1030],[74,1034],[75,1035],[76,10],[77,11],[78,12],[79,13],[80,26],[81,17],
               [82,18],[83,16]]

        print 'Lookup table: {name}'.format(name=os.path.abspath(self.LUT_file))
        LUTlabelsRGBA = np.loadtxt(self.LUT_file, skiprows=4, usecols=[0,1,2,3,4,5], comments='#',
                        dtype={'names': ('index', 'label', 'R', 'G', 'B', 'A'),'formats': ('int', '|S30', 'int', 'int', 'int', 'int')})
        print LUTlabelsRGBA
        self.aparc_aseg_file = os.path.abspath(self.inputs.aparc_aseg_file)
        print 'Aparc path: {name}'.format(name=self.aparc_aseg_file)
        niiAPARCimg = nb.load(self.aparc_aseg_file)
        niiAPARCdata = niiAPARCimg.get_data()
        print 'Aparc Data Extracted'
        niiDataLabels = np.unique(niiAPARCdata)
        print 'Data labels recorded'
        print niiDataLabels

        numDataLabels = np.size(niiDataLabels)
        numLUTLabels = np.size(LUTlabelsRGBA)
        print 'Number of labels in image: {n}'.format(n=numDataLabels)
        print 'Number of labels in LUT: {n}'.format(n=numLUTLabels)
        if numLUTLabels < numDataLabels:
            print 'LUT file provided does not contain all of the regions in the image'
            print 'Removing unmapped regions'

        labelDict = {}
        GMlabelDict = {}
        LUTlabelDict = {}
        mapDict = {}

        ''' Create dictionary for input LUT table'''
        for labels in range(0,numLUTLabels):
            #I'm sure there's a better way of writing the right side of this...
            LUTlabelDict[LUTlabelsRGBA[labels][0]] = [LUTlabelsRGBA[labels][1],LUTlabelsRGBA[labels][2], LUTlabelsRGBA[labels][3], LUTlabelsRGBA[labels][4], LUTlabelsRGBA[labels][5]]


        print 'Printing LUT label dictionary'
        print LUTlabelDict

        """ Create empty grey matter mask, Populate with only those regions defined in the mapping."""
        niiGM = np.zeros( niiAPARCdata.shape, dtype = np.uint8 )
        for ma in MAPPING:
            niiGM[ niiAPARCdata == ma[1]] = ma[0]
            mapDict[ma[0]] = ma[1]

        #print 'Printing Map dictionary'
        #print mapDict

        #print 'Printing GM label dictionary'
        #print LUTlabelDict

        print 'Grey matter mask created'
        greyMaskLabels = np.unique(niiGM)
        numGMLabels = np.size(greyMaskLabels)
        print 'Number of grey matter labels: {num}'.format(num=numGMLabels)
        print greyMaskLabels

        for label in greyMaskLabels:
            del GMlabelDict
            GMlabelDict = {}
            GMlabelDict['labels'] = LUTlabelDict[label][0]
            GMlabelDict['colors']  = [LUTlabelDict[label][1], LUTlabelDict[label][2], LUTlabelDict[label][3]]
            GMlabelDict['a'] = LUTlabelDict[label][4]
            try:
                mapDict[label]
                GMlabelDict['originalID'] = mapDict[label]
            except:
                print 'Label {lbl} not in provided mapping'.format(lbl=label)
            print GMlabelDict
            labelDict[label] = GMlabelDict

        roi_image = nb.Nifti1Image(niiGM, niiAPARCimg.get_affine(), niiAPARCimg.get_header())

        #print 'Printing final label dictionary'
        #print labelDict

        #print 'Printing unique labels in remapped ROI file'
        #print np.unique(roi_image.get_data())

        print 'Saving ROI File to {path}'.format(path=os.path.abspath(self.roi_file))
        nb.save(roi_image, os.path.abspath(self.roi_file))
        print 'Saving Dictionary File to {path} in Pickle format'.format(path=os.path.abspath(self.dict_file))
        file = open(os.path.abspath(self.dict_file), "w")
        pickle.dump(labelDict, file)
        file.close()

        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs["roi_file"] = os.path.abspath(self._gen_outfilename('nii'))
        outputs["dict_file"] = os.path.abspath(self._gen_outfilename('pck'))

        if isdefined(self.inputs.out_roi_file):
            outputs['roi_file'] = os.path.abspath(self.inputs.out_roi_file)

        if isdefined(self.inputs.out_dict_file):
            outputs['dict_file'] = os.path.abspath(self.inputs.out_dict_file)

        return outputs

    def _gen_outfilename(self, ext):
        _, name , _ = split_filename(self.inputs.aparc_aseg_file)
        if self.inputs.use_freesurfer_LUT:
            prefix = "fsLUT"
        elif not self.inputs.use_freesurfer_LUT and isdefined(self.inputs.LUT_file):
            lutpath, lutname, lutext = split_filename(self.inputs.LUT_file)
            prefix = lutname
        return prefix + "_" + name + "." + ext

