
##############################################################################
# Ganga Project. http://cern.ch/ganga
#
# $Id: DQ2Dataset.py,v 1.3 2008-07-28 16:56:30 elmsheus Exp $
###############################################################################
# A DQ2 dataset

import sys, os, re, urllib, commands, imp, threading, time

from Ganga.GPIDev.Lib.Dataset import Dataset
from Ganga.GPIDev.Schema import *
from Ganga.Utility.files import expandfilename
from Ganga.Utility.logging import getLogger

from dq2.common.DQException import *
from dq2.info.TiersOfATLAS import _refreshToACache, ToACache
from dq2.repository.DQRepositoryException import DQUnknownDatasetException
from dq2.location.DQLocationException import DQLocationExistsException
from dq2.common.DQException import DQInvalidRequestException
from dq2.content.DQContentException import DQInvalidFileMetadataException
from dq2.common.client.DQClientException import DQInternalServerException
from dq2.common.dao.DQDaoException import DQDaoException

_refreshToACache()

def listDatasets(name,filter=True):
    '''helper function to filter out temporary datasets'''

    try:
        dq2_lock.acquire()
        datasets = [ (lfn,ids['vuids'][0]) for lfn, ids in dq2.listDatasets(name).iteritems() ]
    finally:
        dq2_lock.release()
        

    if filter:
        re_tmp = re.compile('bnl$|bnlcoll$|sub\d+$|dis\d+$')
        datasets = [ (dsn, vuid) for dsn, vuid in datasets if not re_tmp.search(dsn) ]

    return datasets

def getLocationsCE(locations):
    '''helper function to access the CE associated to a list of locations'''

    ces = []
    for location in locations:
        try:
            temp_ces = ToACache.sites[location]['ce']
            if temp_ces !=[""]:
                ces += temp_ces
        except KeyError:
            pass

    return ces
  
def getIncompleteLocationsCE(locations, minnum = 0):
    '''helper function to access the CE associated to a list of locations from incomplete list '''

    ces = []
    for dataset, info in locations.iteritems():
        for location, num in info.iteritems():
            if num >= minnum:
                try:
                    temp_ces = ToACache.sites[location]['ce']
                    if temp_ces !=[""]:
                        ces += temp_ces
                except KeyError:
                    pass

    return ces

def getIncompleteLocations(locations, minnum = 0):
    '''helper function to access a list of locations from incomplete list '''

    ces = []
    for dataset, info in locations.iteritems():
        for location, num in info.iteritems():
            if num >= minnum:
                ces.append(location)

    return ces


def isDQ2SRMSite(location):
    '''helper function to verify a location'''
    
    try:
        return ToACache.sites[location].has_key('srm')
    except KeyError:
        return False


def dq2_list_locations_siteindex(datasets=[], timeout=15, days=2, replicaList=False, allowed_sites = [] ):

    if datasets.__class__.__name__=='str':
        datasets = [ datasets ]

    dataset_locations_list = { }
    dataset_guid_location_list = {}
    guidLocation = {}
        
    for dataset in datasets:
        try:
            dq2_lock.acquire()
            try:
                locations = dq2.listDatasetReplicas(dataset)
            except:
                logger.error('Dataset %s not found !', dataset)
                return []
        finally:
            dq2_lock.release()
        try:
            dq2_lock.acquire()
            try:
                datasetinfo = dq2.listDatasets(dataset)
            except:
                datasetinfo = {}
        finally:
            dq2_lock.release()

        try:
            datasetvuid = datasetinfo[dataset]['vuids'][0]
        except KeyError:
            logger.warning('Dataset %s not found',dataset)
            return []

        if not locations.has_key(datasetvuid):
            logger.warning('Dataset %s not found',dataset)
            return []

        alllocations = locations[datasetvuid][0] + locations[datasetvuid][1]
        logger.warning('Dataset %s has %s locations', dataset, len(alllocations))

        try:
            dq2_lock.acquire()
            contents = dq2.listFilesInDataset(dataset)
        finally:
            dq2_lock.release()

        if not contents:
            logger.error('Dataset %s is empty.', dataset)
            return

        contents = contents[0]
        guidsDataset = []

        for guid, keys in contents.iteritems():
            guidsDataset.append(guid)
            guidLocation[guid] = []
            

        locations_checktime = {}
        locations_num = {}
        retry = 0
        allchecked = False

        if allowed_sites:
            alllocations = [ site for site in alllocations if site in allowed_sites ]

        while not allchecked and retry<4: 
            for location in alllocations:
                datasetinfo = dq2.listMetaDataReplica(location, dataset)
                if datasetinfo.has_key('checkdate'):
                    checkdate = datasetinfo['checkdate']
                    try:
                        checktime = time.mktime(time.strptime(checkdate,'%Y-%m-%d %H:%M:%S'))
                    except ValueError:    
                        checktime = -time.time()
                else:
                    checktime = -time.time()
                    continue

                if (time.time()-checktime > days*86000): 
                    dq2.checkDatasetConsistency(location, dataset)
                    logger.warning('Please be patient - waiting for site-index update at site %s ...', location)
                    locations_checktime[location] = False
                else:
                    locations_checktime[location] = True                    

            for location, value in locations_checktime.iteritems():
                if not value:
                    allchecked = False
                    break
                else:
                    allchecked = True

            if allchecked:
                break

            retry = retry + 1        
            time.sleep(timeout)

        for location in alllocations:
            datasetsiteinfo = dq2.listFileReplicas(location, dataset)
            numberoffiles = datasetsiteinfo[0]['found']
            locations_num[location]=int(numberoffiles)

            guidsSite = datasetsiteinfo[0]['content']
            for guid in guidsDataset:
                if guid in guidsSite:
                    temp = guidLocation[guid]
                    temp.append(location)
                    guidLocation[guid] = temp

        dataset_locations_list[dataset] = locations_num

    if replicaList:
        return guidLocation
    else:
        return dataset_locations_list


def resolve_container(datasets):
    """Helper function to resolver dataset containers"""
    container_datasets = []
    for dataset in datasets:
        if dataset.endswith("/"):
            try:
                dq2_lock.acquire() 
                try:
                    contents = dq2.listDatasetsInContainer(dataset)
                except:
                    contents = []
            finally:
                dq2_lock.release()
                    
            if not contents:
                contents = []
            container_datasets = container_datasets + contents
    if container_datasets:
        return container_datasets
    else:
        return datasets
    

class DQ2Dataset(Dataset):
    '''ATLAS DDM Dataset'''

    _schema = Schema(Version(1,0), {
        #'dataset'    : SimpleItem(defvalue = '', doc = 'Dataset Name'),
        'dataset'    : SimpleItem(defvalue = [], typelist=['str'], sequence=1, strict_sequence=0, doc="Dataset Name(s)" ),
        #'tagdataset' : SimpleItem(defvalue = '', doc = 'Tag Dataset Name'),
        'tagdataset' : SimpleItem(defvalue = [], typelist=['str'], sequence=1, strict_sequence=0, doc = 'Tag Dataset Name'),
        'use_aodesd_backnav' : SimpleItem(defvalue = False, doc = 'Use AOD to ESD Backnavigation'),
        'names'      : SimpleItem(defvalue = [], typelist=['str'], sequence = 1, doc = 'Logical File Names to use for processing'),
        'exclude_names'      : SimpleItem(defvalue = [], typelist=['str'], sequence = 1, doc = 'Logical File Names to exclude from processing'),
        'number_of_files' : SimpleItem(defvalue = 0, doc = 'Number of files. '),
        'guids'      : SimpleItem(defvalue = [], typelist=['str'], sequence = 1, doc = 'GUID of Logical File Names'),
        'type'       : SimpleItem(defvalue = '', doc = 'Dataset type, DQ2 or LFN'),
        'datatype'   : SimpleItem(defvalue = '', doc = 'Data type: DATA, MC or MuonCalibStream'),
        'accessprotocol'       : SimpleItem(defvalue = '', doc = 'Accessprotocol to use on worker node, e.g. Xrootd'),
        'match_ce_all' : SimpleItem(defvalue = False, doc = 'Match complete and incomplete sources of dataset to CE during job submission'),
        'min_num_files' : SimpleItem(defvalue = 0, doc = 'Number of minimum files at incomplete dataset location'),
        'check_md5sum' : SimpleItem(defvalue = False, doc = 'Check md5sum of input files on storage elemenet - very time consuming !')
    })

    _category = 'datasets'
    _name = 'DQ2Dataset'
    _exportmethods = [ 'list_datasets', 'list_contents', 'list_locations',
                       'list_locations_ce', 'list_locations_num_files',
                       'get_contents', 'get_locations', 'list_locations_siteindex' ]

    _GUIPrefs = [ { 'attribute' : 'dataset',        'widget' : 'String_List' },
                  { 'attribute' : 'tagdataset',     'widget' : 'String_List' },
                  { 'attribute' : 'names',          'widget' : 'String_List' },
                  { 'attribute' : 'exclude_names',          'widget' : 'String_List' },
                  { 'attribute' : 'number_of_files', 'widget' : 'String' },
                  { 'attribute' : 'guids',           'widget' : 'String_List' },
                  {'attribute'  : 'type',            'widget' : 'String_Choice', 'choices':['DQ2_LOCAL', 'DQ2_DOWNLOAD', 'TAG', 'LFC', 'DQ2_COPY' ]},
                  { 'attribute' : 'datatype',        'widget' : 'String_Choice', 'choices':['DATA', 'MC', 'MuonCalibStream' ]},
                  {'attribute'  : 'accessprotocol',  'widget' : 'String' },
                  { 'attribute' : 'match_ce_all',    'widget' : 'Bool' },
                  { 'attribute' : 'min_num_files',   'widget' : 'Int' },
                  { 'attribute' : 'check_md5sum',    'widget' : 'Bool' } ]

    def __init__(self):
        super( DQ2Dataset, self ).__init__()

    def dataset_exists(self):

        if not self.dataset: return False

        for dataset in self.dataset:
            try:
                dq2_lock.acquire()
                try:
                    state = dq2.getState(dataset)
                except:
                    state = None
            finally:
                dq2_lock.release()
            if not state:
                break

        return not state is None

    def tagdataset_exists(self):

        if not self.tagdataset: return False

        for tagdataset in self.tagdataset:
            try:
                dq2_lock.acquire()
                try:
                    state = dq2.getState(tagdataset)
                except DQUnknownDatasetException:
                    state = None
            finally:
                dq2_lock.release()
            if not state:
                break

        return not state is None
    
    def get_contents(self,backnav=False, overlap=True):
        '''Helper function to access dataset content'''

        allcontents = []
        diffcontents = {}

        datasets = resolve_container(self.dataset)

        for dataset in datasets:
            if backnav:
                dataset = re.sub('AOD','ESD',dataset)

            try:
                dq2_lock.acquire()
                try:
                    contents = dq2.listFilesInDataset(dataset)
                except:
                    contents = []
                    pass
            finally:
                dq2_lock.release()

            if not contents:
                contents = []
                pass

            # Convert 0.3 output to 0.2 style
            contents = contents[0]
            contents_new = []
            for guid, info in contents.iteritems():
                contents_new.append( (guid, info['lfn']) )
            contents = contents_new

            if backnav:
                return contents

            # Process only certain filenames ?
            if self.names:
                job = self.getJobObject()
                contents = [ (guid,lfn) for guid, lfn in contents if lfn in job.inputdata.names ]

            # Exclude certain filenames ?
            if self.exclude_names:
                job = self.getJobObject()
                contents = [ (guid,lfn) for guid, lfn in contents if not lfn in job.inputdata.exclude_names ]

            # Exclude log files
            contents = [ (guid,lfn) for guid, lfn in contents if not lfn.endswith('log.tgz') ]
                

            # Process only certain number of files ?
            if self.number_of_files:
                numfiles = self.number_of_files
                if numfiles.__class__.__name__ == 'str':
                     numfiles = int(numfiles)

                if numfiles>0 and numfiles<len(contents):
                    contents_new = []
                    for i in xrange(0,numfiles):
                        contents_new.append(contents[i])

                    contents = contents_new

            allcontents = allcontents + contents
            diffcontents[dataset] = contents
            
        self.number_of_files = len(allcontents)
        if overlap:
            return allcontents
        else:
            return diffcontents
        

    def get_tag_contents(self):
        '''Helper function to access tag datset content'''

        allcontents = []

        datasets = resolve_container(self.tagdataset)
        
        for tagdataset in datasets:
            try:
                dq2_lock.acquire()
                contents=dq2.listFilesInDataset(tagdataset)
            finally:
                dq2_lock.release()

            if not contents:
                return [] # protects against crash in next line if contents is empty
            # Convert 0.3 output to 0.2 style
            contents = contents[0]
            contents_new = []
            for guid, info in contents.iteritems():
                contents_new.append( (guid, info['lfn']) )
            allcontents = allcontents + contents_new

        return allcontents

    def get_locations(self, complete=0, backnav=False, overlap=True):
        '''helper function to access the dataset location'''

        alllocations = {}
        overlaplocations = []

        datasets = resolve_container(self.dataset)
        
        for dataset in datasets:
            if backnav:
                dataset = re.sub('AOD','ESD',dataset)

            try:
                dq2_lock.acquire()
                try:
                    locations = dq2.listDatasetReplicas(dataset)
                except:
                    logger.error('Dataset %s not found !', dataset)
                    return []
            finally:
                dq2_lock.release()
            try:
                dq2_lock.acquire()
                try:
                    datasetinfo = dq2.listDatasets(dataset)
                except:
                    datasetinfo = {}
            finally:
                dq2_lock.release()

            try:
                datasetvuid = datasetinfo[dataset]['vuids'][0]
            except KeyError:
                logger.warning('Dataset %s not found',dataset)
                return []

            if not locations.has_key(datasetvuid):
                logger.warning('Dataset %s not found',dataset)
                return []
            if complete==0:
                templocations = locations[datasetvuid][0] + locations[datasetvuid][1]
            else:
                templocations = locations[datasetvuid][1]

            alllocations[dataset] = templocations

            if overlaplocations == []:
                overlaplocations = templocations

            overlaplocations_temp = []    
            for location in templocations:
                if location in overlaplocations:
                    overlaplocations_temp.append(location)
            overlaplocations = overlaplocations_temp

        if overlap:
            return overlaplocations
        else:
            return alllocations

    def list_datasets(self,name,filter=True):
        '''List datasets names'''

        datasets = listDatasets(name,filter)
        if not datasets:
            logger.error('No datasets found.')
            return

        for dsn, vuid in datasets:
            print dsn

    def list_contents(self,dataset=None):
        '''List dataset content'''

        if not dataset:
            datasets = self.dataset
        else:
            datasets = [ dataset ]

        for dataset in datasets:
            try:
                dq2_lock.acquire()
                contents = dq2.listFilesInDataset(dataset)
            finally:
                dq2_lock.release()

            if not contents:
                print 'Dataset %s is empty.' % dataset
                return

            print 'Dataset %s' % dataset
            contents = contents[0]
            for guid, info in contents.iteritems():
                print '    %s' % info['lfn']
            print 'In total %d files' % len(contents)

    def list_locations(self,dataset=None,complete=0):
        '''List dataset locations'''

        if not dataset:
            datasets = self.dataset
        else:
            datasets = [ dataset ]

        datasets = resolve_container(datasets)

        for dataset in datasets:
            try:
                dq2_lock.acquire()
                try:
                    locations = dq2.listDatasetReplicas(dataset,complete)
                except DQUnknownDatasetException:
                    logger.error('Dataset %s not found !', dataset)
                    return
                except DQDaoException:
                    completestr = 'complete'
                    if not complete: completestr = 'incomplete'

                    logger.error('Dataset %s has no %s location', dataset, completestr)
                    return

            finally:
                dq2_lock.release()

            try:
                dq2_lock.acquire()
                datasetinfo = dq2.listDatasets(dataset)
            finally:
                dq2_lock.release()

            datasetvuid = datasetinfo[dataset]['vuids'][0]

            if not locations.has_key(datasetvuid):
                print 'Dataset %s not found' % dataset
                return

            locations = locations[datasetvuid]

            print 'Dataset %s' % dataset
            if len(locations[1]): print 'Complete:', ' '.join(locations[1])
            if len(locations[0]): print 'Incomplete:', ' '.join(locations[0])

    def list_locations_ce(self,dataset=None,complete=0):
        '''List the CE associated to the dataset location'''

        if not dataset:
            datasets = self.dataset
        else:
            datasets = dataset

        datasets = resolve_container(datasets)

        for dataset in datasets:
            try:
                dq2_lock.acquire()
                try:
                    locations = dq2.listDatasetReplicas(dataset,complete)
                except DQUnknownDatasetException:
                    logger.error('Dataset %s not found !', dataset)
                    return
            finally:
                dq2_lock.release()

            try:
                dq2_lock.acquire()
                datasetinfo = dq2.listDatasets(dataset)
            finally:
                dq2_lock.release()

            datasetvuid = datasetinfo[dataset]['vuids'][0]

            if not locations.has_key(datasetvuid):
                print 'Dataset %s not found' % dataset
                return
            locations = locations[datasetvuid]

            print 'Dataset %s' % dataset
            if len(locations[1]): print 'Complete:', ' '.join(getLocationsCE(locations[1]))
            if len(locations[0]): print 'Incomplete:', ' '.join(getLocationsCE(locations[0]))

    def list_locations_num_files(self,dataset=None,complete=-1,backnav=False):
        '''List the number of files replicated to the dataset locations'''

        if not dataset:
            datasets = self.dataset
        else:
            datasets = [ dataset ]
            
        datasets = resolve_container(datasets)

        dataset_locations_num = {}
        for dataset in datasets:
            if backnav:
                dataset = re.sub('AOD','ESD',dataset)

            locations_num = {}
            from Ganga.Utility.GridShell import getShell
            gridshell = getShell()
            gridshell.env['LFC_CONNTIMEOUT'] = '45'
            exe = os.path.join(os.path.dirname(__file__)+'/ganga-readlfc.py')        
            cmd= exe + " %s %s " % (dataset, complete) 
            rc, out, m = gridshell.cmd1(cmd,allowed_exit=[0,142])

            if rc == 0 and not out.startswith('ERROR'):
                for line in out.split():
                    if line.startswith('#'):
                        info = line[1:].split(':')
                        if len(info)==2:
                            locations_num[info[0]]=int(info[1])
            elif rc==142:
                logger.error("LFC file catalog query time out - Retrying...")
                removelfclist = ""
                while rc!=0:
                    output = out.split()
                    try:
                        removelfc = output.pop()
                        if removelfclist == "":
                            removelfclist=removelfc
                        else:
                            removelfclist= removelfclist+","+removelfc
                    except IndexError:
                        logger.error("Empty LFC string of broken catalogs")
                        return {}
                    cmd = exe + " -r " + removelfclist + " %s %s" % (dataset, complete)
                    rc, out, m = gridshell.cmd1(cmd,allowed_exit=[0,142])

                if rc == 0 and not out.startswith('ERROR'):
                    for line in out.split():
                        if line.startswith('#'):
                            info = line[1:].split(':')
                            if len(info)==2:
                                locations_num[info[0]]=int(info[1])

            dataset_locations_num[dataset] = locations_num
        return dataset_locations_num

    def get_replica_listing(self,dataset=None,SURL=True,complete=0,backnav=False):
        '''Return list of guids/surl replicated dependent on dataset locations'''
        if not dataset:
            datasets = self.dataset
        else:
            datasets = [ dataset ]

        datasets = resolve_container(datasets)

        dataset_locations_list = {}
        for dataset in datasets:
            if backnav:
                dataset = re.sub('AOD','ESD',dataset)

            locations_list = {}
            from Ganga.Utility.GridShell import getShell
            gridshell = getShell()
            gridshell.env['LFC_CONNTIMEOUT'] = '45'
            exe = os.path.join(os.path.dirname(__file__)+'/ganga-readlfc.py')

            if SURL:
                cmd= exe + " -l %s %s " % (dataset, complete)
            else:
                cmd= exe + " -g %s %s " % (dataset, complete) 
            rc, out, m = gridshell.cmd1(cmd,allowed_exit=[0,142])

            if rc == 0 and not out.startswith('ERROR'):
                for line in out.split():
                    if line.startswith('#'):
                        info = line[1:].split(',')
                        if len(info)>1:
                            locations_list[info[0]]=info[1:]
            elif rc==142:
                logger.error("LFC file catalog query time out - Retrying...")
                removelfclist = ""
                while rc!=0:
                    output = out.split()
                    try:
                        removelfc = output.pop()
                        if removelfclist == "":
                            removelfclist=removelfc
                        else:
                            removelfclist= removelfclist+","+removelfc
                    except IndexError:
                        logger.error("Empty LFC string of broken catalogs")
                        return {}
                    cmd = exe + " -l -r " + removelfclist + " %s %s" % (dataset, complete)
                    rc, out, m = gridshell.cmd1(cmd,allowed_exit=[0,142])

                if rc == 0 and not out.startswith('ERROR'):
                    for line in out.split():
                        if line.startswith('#'):
                            info = line[1:].split(',')
                            if len(info)>1:
                                locations_list[info[0]]=info[1:]

            dataset_locations_list[dataset] = locations_list

        if dataset:
            return dataset_locations_list[dataset]
        else:
            return dataset_locations_list

    def list_locations_siteindex(self,dataset=None, timeout=15, days=2, replicaList=False):

        if not dataset:
            datasets = self.dataset
        else:
            datasets = [ dataset ]

        datasets = resolve_container(datasets)

        return dq2_list_locations_siteindex(datasets, timeout, days, replicaList)



class DQ2OutputDataset(Dataset):
    """DQ2 Dataset class for a dataset of output files"""
    
    _schema = Schema(Version(1,0), {
        'outputdata'     : SimpleItem(defvalue = [], typelist=['str'], sequence=1, doc='Output files to be returned via SE'), 
        'output'         : SimpleItem(defvalue = [], typelist=['str'], sequence = 1, protected=1, doc = 'Output information automatically filled by the job'),
        'datasetname'    : SimpleItem(defvalue='', doc='Name of the DQ2 output dataset automatically filled by the job'),
        'datasetList'    : SimpleItem(defvalue = [], typelist=['str'],  sequence = 1,protected=1, doc='List of DQ2 output datasets automatically filled by the AthenaMC job'),
        'location'       : SimpleItem(defvalue='',doc='SE output path location'),
        'local_location' : SimpleItem(defvalue='',doc='Local output path location'),
        'use_datasetname' : SimpleItem(defvalue = False, doc = 'Use datasetname as it is and do not prepend users.myname.ganga'),
        'use_shortfilename' : SimpleItem(defvalue = False, doc = 'Use shorter version of filenames and do not prepend users.myname.ganga')
        })
    
    _category = 'datasets'
    _name = 'DQ2OutputDataset'

    _exportmethods = [ 'retrieve', 'fill', 'create_dataset','create_datasets', 'dataset_exists', 'get_locations' ]

    _GUIPrefs = [ { 'attribute' : 'outputdata',     'widget' : 'String_List' },
                  { 'attribute' : 'output',         'widget' : 'String_List' },
                  { 'attribute' : 'datasetname',    'widget' : 'String' },
                  { 'attribute' : 'datasetList',    'widget' : 'String_List' },
                  { 'attribute' : 'location',       'widget' : 'String_List' },
                  { 'attribute' : 'local_location', 'widget' : 'File' },
                  { 'attribute' : 'use_datasetname',    'widget' : 'Bool' },
                  { 'attribute' : 'use_shortfilename',    'widget' : 'Bool' }
                  ]
    
    def __init__(self):
        super(DQ2OutputDataset, self).__init__()

    def dataset_exists(self, datasetname = None):
        """Check if dataset already exists"""
        exist = False
        if not datasetname: datasetname=self.datasetname
        try:
            dq2_lock.acquire()
            try:
                content = dq2.listDatasets(datasetname)
            except:
                content = []
        finally:
            dq2_lock.release()
        if len(content)>0:
            exist = True
            
        return exist

    def get_locations(self, datasetname = None, complete=0, quiet = False):
        '''helper function to access the dataset location'''

        if not datasetname: datasetname=self.datasetname

        try:
            dq2_lock.acquire()
            try:
                locations = dq2.listDatasetReplicas(datasetname)
            except:
                logger.error('Dataset %s not found !', datasetname)
                return
        finally:
            dq2_lock.release()
        try:
            dq2_lock.acquire()
            datasetinfo = dq2.listDatasets(datasetname)
        finally:
            dq2_lock.release()

        datasetvuid = datasetinfo[datasetname]['vuids'][0]
            
        if not locations.has_key(datasetvuid):
            logger.warning('Dataset %s not found',datasetname)
            return []
        if complete==0:
            return locations[datasetvuid][0] + locations[datasetvuid][1]
        else:
            return locations[datasetvuid][1]

    def create_dataset(self, datasetname = None):
        """Create dataset in central DQ2 database"""

        if datasetname:
            try:
                dq2_lock.acquire()
                dq2.registerNewDataset(datasetname)
            finally:
                dq2_lock.release()

            self.datasetname = datasetname

    def create_datasets(self, datasets):
        # first, ensure uniqueness of name
        for dataset in datasets:
            if dataset not in self.datasetList:
                self.datasetList.append(dataset)
        for dataset in self.datasetList:
            try:
                dq2_lock.acquire()
                content = dq2.listDatasets(dataset)
            finally:
                dq2_lock.release()
            if len(content)>0:
                logger.warning("dataset %s already exists: skipping", dataset)
                continue
            logger.debug("creating dataset: %s", dataset)
            self.create_dataset(dataset)
        
        self.datasetname="" # mandatory to avoid confusing the fill method
        return
        
    def register_dataset_location(self, datasetname, siteID):
        """Register location of dataset into DQ2 database"""

        try:
            dq2_lock.acquire()
            content = dq2.listDatasets(datasetname)
        finally:
            dq2_lock.release()

        if content=={}:
            logger.error('Dataset %s is not defined in DQ2 database !',datasetname)
            return

        try:
            dq2_lock.acquire()
            if dq2.listDatasetReplicas(datasetname)=={}: 
                dq2.registerDatasetLocation(datasetname, siteID)
        finally:
            dq2_lock.release()

        return

    def register_file_in_dataset(self,datasetname,lfn,guid, size, checksum):
        """Add file to dataset into DQ2 database"""
        # Check if dataset really exists

        try:
            dq2_lock.acquire()
            content = dq2.listDatasets(datasetname)
        finally:
            dq2_lock.release()

        if content=={}:
            logger.error('Dataset %s is not defined in DQ2 database !',datasetname)
            return
        # Add file to DQ2 dataset
        ret = []
        #sizes = []
        #checksums = []
        #for i in xrange(len(lfn)):
        #    sizes.append(None)
        #    checksums.append(None)
        
        try:
            dq2_lock.acquire()
            try:
                ret = dq2.registerFilesInDataset(datasetname, lfn, guid, size, checksum) 
            except (DQInvalidFileMetadataException, DQInvalidRequestException), Value:
                logger.warning('Warning, some files already in dataset: %s', Value)
                pass
        finally:
            dq2_lock.release()

        return 

    def register_datasets_details(self,datasets,outdata):

        reglines=[]
        for line in outdata:
            try:
                #[dataset,lfn,guid,siteID]=line.split(",")
                [dataset,lfn,guid,size,md5sum,siteID]=line.split(",")
            except ValueError:
                continue
            size = long(size)
            md5sum = 'md5:'+md5sum
            siteID=siteID.strip() # remove \n from last component
            regline=dataset+","+siteID
            if regline in reglines:
                logger.info("Registration of %s in %s already done, skipping" % (dataset,siteID))
                #continue
            else:
                reglines.append(regline)
                logger.info("Registering dataset %s in %s" % (dataset,siteID))
                # use another version of register_dataset_location, as the "secure" one does not allow to keep track of datafiles saved in the fall-back site (CERNCAF)
                try:
                    dq2_lock.acquire()
                    content = dq2.listDatasets(dataset)
                finally:
                    dq2_lock.release()

                if content=={}:
                    logger.error('Dataset %s is not defined in DQ2 database !',dataset)
                else: 
                    try:
                        dq2_lock.acquire()
                        try:
                            dq2.registerDatasetLocation(dataset, siteID)
                        except DQLocationExistsException, DQInternalServerException:
                            logger.debug("Dataset %s is already registered at location %s", dataset, siteID )
                        
                    finally:
                        dq2_lock.release()

                        
            self.register_file_in_dataset(dataset,[lfn],[guid],[size],[md5sum])

    def fill(self, type=None, name=None, **options ):
        """Determine outputdata and outputsandbox locations of finished jobs
        and fill output variable"""

        from Ganga.GPIDev.Lib.Job import Job
        from GangaAtlas.Lib.ATLASDataset import filecheck

        job = self._getParent()

#       Determine local output path to store files
        if job.outputdata.local_location:
            outputlocation = expandfilename(job.outputdata.local_location)
        elif job.outputdata.location and ((job.backend._name == 'Local') or (job.backend._name == 'LSF') or (job.backend._name == 'PBS') or (job.backend._name == 'SGE')):
            outputlocation = expandfilename(job.outputdata.location)
        else:
            try:
                tmpdir = os.environ['TMPDIR']
            except:
                tmpdir = '/tmp/'
            outputlocation = tmpdir

#       Output files on SE
        outputfiles = job.outputdata.outputdata
        
#       Search output_guid files from LCG jobs in outputsandbox
        jobguids = []

        if (job.backend._name == 'LCG' ) or (job.backend._name == 'Local') or (job.backend._name == 'LSF') or (job.backend._name == 'PBS') or (job.backend._name == 'SGE'):
            pfn = job.outputdir + "output_guids"
            fsize = filecheck(pfn)
            if (fsize>0):
                jobguids.append(pfn)
                logger.debug('jobguids: %s', jobguids)
                
            
#       Get guids from output_guid files
            for ijobguids in jobguids: 
                f = open(ijobguids)
                templines =  [ line.strip() for line in f ]
                if not self.output:
                    for templine in templines:
                        tempguid = templine.split(',')
                        #self.output = self.output + tempguid

                f.close()

#       Get output_location
            pfn = job.outputdir + "output_location"
            fsize = filecheck(pfn)
            if (fsize>0):
                f = open(pfn)
                line = f.readline()
                self.location = line.strip()
                f.close()
                
                #  Register DQ2 location
                # FMB: protection against empty strings
                if self.datasetname : 
                    self.register_dataset_location(self.datasetname, self.location)
                    
            pfn = job.outputdir + "output_data"
            fsize = filecheck(pfn)
            if fsize>0:
                f=open(pfn)
                self.output+=f.readlines()
                f.close()
                    
#       Local host execution
        if (job.backend._name == 'Local' or \
            job.backend._name == 'LSF' or \
            job.backend._name == 'PBS' or \
            job.backend._name == 'SGE'):
            for file in outputfiles:
                pfn = outputlocation+"/"+file
                fsize = filecheck(pfn)
                if (fsize>0):
                    self.output.append(pfn)

#       Output files in the sandbox 
        outputsandboxfiles = job.outputsandbox
        for file in outputsandboxfiles:
            pfn = job.outputdir+"/"+file
            fsize = filecheck(pfn)
            if (fsize>0):
                self.output.append(pfn)

#       Master job finish
        if not job.master and job.subjobs:
            self.location = []
            self.output = []
            for subjob in job.subjobs:
                self.output+=subjob.outputdata.output
                self.datasetname=subjob.outputdata.datasetname
                self.location.append(subjob.outputdata.location)
        else:
            # AthenaMC: register dataset location and insert file in dataset only within subjobs (so that if one subjob fails, the master job fails, but the dataset is saved...). Master job completion does not do anything...
            self.register_datasets_details(self.datasetname,self.output)
            

    def retrieve(self, type=None, name=None, **options ):
        """Retrieve files listed in outputdata and registered in output from
        remote SE to local filesystem in background thread"""
        from Ganga.GPIDev.Lib.Job import Job
        from GangaAtlas.Lib.ATLASDataset import Download
        import os, threading
        
        job = self._getParent()

        if job.backend._name == 'LCG':
            Download.prefix_hack = job.backend.middleware
        else:
            Download.prefix_hack = 'EDG'

        os.environ['DQ2_URL_SERVER'] = config['DQ2_URL_SERVER']
        os.environ['DQ2_URL_SERVER_SSL'] = config['DQ2_URL_SERVER_SSL']
        
        if not os.environ.has_key('DQ2_LOCAL_ID'):
            os.environ['DQ2_LOCAL_ID'] = "DUMMY"
        if not os.environ.has_key('DQ2_COPY_COMMAND'):
            os.environ['DQ2_COPY_COMMAND']="lcg-cp --vo atlas"

        if job.outputdata.outputdata and (job.backend._name == 'LCG') and job.outputdata.output:
            # Determine local output path to store files
            local_location = options.get('local_location')

            if job._getRoot().subjobs:
                id = "%d" % (job._getRoot().id)
            else:
                id = "%d" % job.id

            if local_location:
                outputlocation = expandfilename(local_location)             
                try:
                    outputlocation = os.path.join( outputlocation, id )
                    os.makedirs(outputlocation)
                except OSError:
                    pass
            elif job.outputdata.local_location:
                outputlocation = expandfilename(job.outputdata.local_location)
                try:
                    outputlocation = os.path.join( outputlocation, id )
                    os.makedirs(outputlocation)
                except OSError:
                    pass
            else:
                # User job repository location
                outputlocation = job.outputdir
            

            exe = 'dq2-get -L CERN -d -D '
            cmd = '%s -H %s %s ' %(exe,outputlocation, job.outputdata.datasetname)

            logger.warning("Please be patient - background execution of dq2-get of %s to %s", job.outputdata.datasetname, outputlocation )

            threads=[]
            thread = Download.download_dq2(cmd)
            thread.setDaemon(True)
            thread.start()
            threads.append(thread)
                
            #for thread in threads:
            #    thread.join()

        else:
            logger.error("Nothing to download")


class DQ2Output(DQ2Dataset):
    '''ATLAS DDM Output Dataset'''
                                                                                                                              
    _schema = Schema(Version(1,0), {
        'dataset'       : SimpleItem(defvalue = '', doc = 'Dataset Name'),
        'names'         : SimpleItem(defvalue = [], sequence = 1, doc = 'Logical File Names'),
        'type'          : SimpleItem(defvalue = '', doc = 'Output Type'),
        'destinationSE' : SimpleItem(defvalue = '', doc = 'Output to SE')
    })
                                                                                                                              
    _category = 'output'
    _name = 'DQ2Output'
    _exportmethods = [ 'list_datasets', 'list_contents', 'list_locations']
                                                                                                                              
    def __init__(self):
        super(DQ2Output,self).__init__()

logger = getLogger()

from dq2.clientapi.DQ2 import DQ2
dq2=DQ2()

from threading import Lock
dq2_lock = Lock()

from Ganga.Utility.Config import makeConfig, ConfigError
config = makeConfig('DQ2', 'DQ2 configuration options')

try:
    config.addOption('DQ2_URL_SERVER', os.environ['DQ2_URL_SERVER'], 'FIXME')
except KeyError:
    config.addOption('DQ2_URL_SERVER', 'http://atlddmcat.cern.ch/dq2/', 'FIXME')
try:
    config.addOption('DQ2_URL_SERVER_SSL', os.environ['DQ2_URL_SERVER_SSL'], 'FIXME')
except KeyError:
    config.addOption('DQ2_URL_SERVER_SSL', 'https://atlddmcat.cern.ch:443/dq2/', 'FIXME')


config.addOption('DQ2_OUTPUT_SPACE_TOKENS', [ 'ATLASUSERDISK' , 'ATLASUSERTAPE', 'ATLASLOCALGROUPDISK'] , 'Allowed space tokens names of DQ2OutputDataset output' )

config.addOption('DQ2_OUTPUT_LOCATIONS', [ 'CERN-PROD_USERTAPE' ], 'Default locations of DQ2OutputDataset output' )

config.addOption('DQ2_BACKUP_OUTPUT_LOCATIONS', [ 'CERN-PROD_USERTAPE', 'FZKDISK', 'LYONDISK', 'PICDISK', 'CNAFDISK', 'RALDISK', 'SARADISK', 'ASGCDISK', 'TRIUMFDISK' ], 'Default backup locations of DQ2OutputDataset output' )



baseURLDQ2 = config['DQ2_URL_SERVER']
baseURLDQ2SSL = config['DQ2_URL_SERVER_SSL']
   
verbose = False

#$Log: not supported by cvs2svn $
#Revision 1.2  2008/07/28 14:27:34  elmsheus
#* Upgrade to DQ2Clients 0.1.17 and DQ2 API
#* Add full support for DQ2 container datasets in DQ2Dataset
#* Change in DQ2OutputDataset.retrieve(): use dq2-get
#* Fix bug #39286: Athena().atlas_environment omits type_list
#
#Revision 1.1  2008/07/17 16:41:18  moscicki
#migration of 5.0.2 to HEAD
#
#the doc and release/tools have been taken from HEAD
#
#Revision 1.72.2.15  2008/07/12 08:58:12  elmsheus
#* DQ2JobSplitter.py: Add numsubjobs option - now jobs can also be
#  splitted by number of subjobs
#* Athena.py: Introduce Athena.atlas_exetype, choices: ATHENA, PYARA, ROOT
#  Execute the following executable on worker node:
#  ATHENA: athena.py jobsOptions input.py
#  PYARA: python jobOptions
#  ROOT: root -q -b jobOptions
#* ganga-stage-in-out-dq2.py: produce now in parallel to input.py also a
#  flat file input.txt containing the inputfiles list. This files can be
#  read in but PYARA or ROOT application flow
#* Change --split and --splitfiles to use DQ2JobSplitter if LCG backend is used
#* Add --athena_exe ATHENA or PYARA or ROOT (see above)
#
#Revision 1.72.2.14  2008/07/10 16:36:58  elmsheus
#Add allowed_sites to dq2_list_locations_siteindex
#
#Revision 1.72.2.13  2008/07/10 06:26:12  elmsheus
#* athena-lch.sh: Fix problems with some DPM sites in athena v14
#Hurng-Chuns updates:
#* BOOT.py/Athena.py: improvements of cmtconfig magic function
#* DQ2Dataset.py: Fix wrong return value of get_contents
#
#Revision 1.72.2.12  2008/06/27 14:24:22  elmsheus
#* DQ2JobSplitter: Change from AMGA siteindex to location file catalog
#* Expand and fix DQ2Dataset.list_location_siteindex()
#* Correct Local() backend dataset list problem, bug #38202
#* Change pybin behaviour in athena-local.sh and athena-lcg.sh
#
#Revision 1.72.2.11  2008/05/12 15:55:38  elmsheus
#Fix small typo
#
#Revision 1.72.2.10  2008/05/12 09:36:35  elmsheus
#Change sh to python for dq2_get
#
#Revision 1.72.2.9  2008/05/12 09:07:31  elmsheus
#Add SGE output support
#
#Revision 1.72.2.8  2008/05/01 16:36:06  elmsheus
#Migrate GangaAtlas-4-4-12 changes
#
#Revision 1.72.2.7  2008/04/01 13:33:32  elmsheus
#* New feature: DQ2Dataset and all other routine support multiple
#  datasets
#* Update athena 14 support
#* Change from ccdcapatlas to ccdcache for LYON
#* Add addition SE for BEIJING
#* Fix AtlasPoint1 setup problem in athena-lcg.sh and athena-local.sh
#
#Revision 1.72.2.6  2008/03/28 15:31:19  elmsheus
#* Add DQ2Dataset.list_locations_siteindex
#* Add extra BEIJING SE
#
#Revision 1.72.2.5  2008/03/27 13:53:30  elmsheus
#* Updates for DQ2_COPY
#* Updates for v13 TAGs
#* Remove setting of X509_CERT_DIR during start-up
#* Add additional exception in DQ2Dataset
#* New version of dq2_get
#
#Revision 1.72.2.4  2008/03/20 12:53:42  elmsheus
#* Apply GangaAtlas-4-16 update
#* New option DQ2Dataset.type='DQ2_COPY'
#  copies input file from SE to worker node instead of Posix I/O
#* Fix configuration option problems
#
#Revision 1.75  2008/03/19 13:15:53  elmsheus
#Fix AOD/ESD backnavigation problem
#
#Revision 1.72.2.3  2008/03/07 20:26:22  elmsheus
#* Apply Ganga-5-0-restructure-config-branch patch
#* Move GangaAtlas-4-15 tag to GangaAtlas-5-0-branch
#
#Revision 1.72.2.2  2008/02/18 11:03:22  elmsheus
#Copy GangaAtlas-4-13 to GangaAtlas-5-0-branch and config updates
#
#Revision 1.74  2008/01/22 08:29:34  elmsheus
#Export get_contents
#
#Revision 1.73  2008/01/07 13:44:40  elmsheus
#* Add option 'check_md5sum' to DQ2Dataset to enable md5sum checking
#  of inputfiles on worker node
#* Add option 'datatype' = 'MC' or 'DATA' to enable reading of cosmics
#  data (like M5 data)
#* Fix typo in ganga-stage-in-out-dq2.py affecting DQ2_LOCAL mode
#
#Revision 1.72  2007/11/12 14:34:28  elmsheus
#Add list guid/location option
#
#Revision 1.71  2007/11/06 07:43:32  elmsheus
#Fix type in tagdataset_exists
#
#Revision 1.70  2007/09/28 12:31:35  elmsheus
#Add local_location option to retrieve method
#
#Revision 1.69  2007/09/26 09:14:47  elmsheus
#Introduce DQ2OutputDataset.use_shortfilename
#
#Revision 1.68  2007/09/25 21:40:27  liko
#Improve error messages
#
#Revision 1.67  2007/09/24 08:42:10  elmsheus
#Apply patches to migrate to Ganga.Utility.GridShell
#
#Revision 1.66  2007/09/11 12:31:49  elmsheus
#Introduce DQ2OutputDataset.use_datasetname=True to allow fully user defined
#output dataset names
#
#Revision 1.65  2007/09/03 00:31:42  elmsheus
#Fix Athena submission error for min_num_files
#
#Revision 1.64  2007/08/02 09:11:30  elmsheus
#* Add ignorefailed variable to AthenaOutputMerger
#* Add 'numfiles_subjob' variable to AthenaSplitterJob
#  Enables job splitting based on the number of files per job
#* Fix logic of j.inputdata.match_ce_all and j.inputdata.min_num_files>X
#  Now min_num_files is chosen over match_ce_all
#* Display complete+incomplete locations as default of
#  DQ2Dataset.list_locations_num_files()
#* Change TAG usage:
#  - j.inputdata.type='TAG' is used now for TAG/AOD reading and ntuple output
#  - j.inputdata.type='TAG_REC' is now used for TAG/AOD reading and
#    AOD production via RecExCommon_topOptions.py
#
#Revision 1.63  2007/07/30 08:41:27  elmsheus
#Move new Merging to main branch
#
#Revision 1.62  2007/07/18 14:23:35  elmsheus
#merge from brach
#
#Revision 1.61  2007/07/13 13:31:39  fbrochu
#get_contents and get_tag_contents methods: protected against crash following failed call to dq2.listFilesInDatasets
#
#Revision 1.60.6.1  2007/07/17 15:24:36  elmsheus
#* Migrate to new RootMerger
#* Fix DQ2OutputLocation path problem
#
#Revision 1.60.6.1  2007/07/17 15:24:36  elmsheus
#* Migrate to new RootMerger
#* Fix DQ2OutputLocation path problem
#
#Revision 1.60  2007/07/03 07:21:35  elmsheus
#Increase LFC_CONNTIMEOUT
#
#Revision 1.59  2007/07/02 12:49:01  elmsheus
#Fix DQ2Dataset.list_locations() exception output
#
#Revision 1.58  2007/06/28 15:58:58  elmsheus
#Fix get_tag_contents
#
#Revision 1.57  2007/06/21 09:32:27  elmsheus
#Change to 0.3 catalogs
#
#Revision 1.56  2007/06/19 16:06:28  elmsheus
#Fix DQ2OutputDataset.get_locations
#
#Revision 1.55  2007/06/13 16:30:35  elmsheus
#Migrate to DQClient 0.3
#
#Revision 1.54  2007/06/07 14:32:01  elmsheus
#Improve LFC reading if timeout occurs
#
#Revision 1.53  2007/05/31 10:06:45  elmsheus
#Add get_replica_listing method for site replica listing
#
#Revision 1.52  2007/05/30 19:50:06  elmsheus
#Introduce AOD->ESD back navigation
#
#Revision 1.51  2007/05/23 08:03:19  elmsheus
#Small fix
#
#Revision 1.50  2007/05/22 19:10:06  elmsheus
#Small fixes for LFC bulk reading
#
#Revision 1.49  2007/05/22 13:50:19  elmsheus
#Add timeout and work-around for broken LFCs
#
#Revision 1.48  2007/05/10 09:07:38  elmsheus
#Add -a option for dq2_get
#
#Revision 1.47  2007/05/08 20:42:22  elmsheus
#Add xrootd accessprotocol
#
#Revision 1.46  2007/05/02 11:34:59  fbrochu
#Removed double registration of dataset in fill() method for AthenaMC (leading to DQ2 warnings when the master job completes). Also extended register_dataset_details (pure AthenaMC method) to allow registration of alternative locations for datasets
#
#Revision 1.45  2007/04/30 18:37:06  elmsheus
#Add get_loations to DQ2OutputDataset
#
#Revision 1.44  2007/04/30 17:47:35  elmsheus
#Add dataset_exists to DQ2Outputdatasets
#
#Revision 1.43  2007/04/26 13:55:38  elmsheus
#Add min_num_files
#
#Revision 1.42  2007/04/26 13:14:55  elmsheus
#Add getIncompleteLocationCE
#
#Revision 1.41  2007/04/26 12:44:19  elmsheus
#Add list_locations_num_files, LFC bulk reading dataset content
#
#Revision 1.40  2007/04/19 13:06:41  elmsheus
#Add threading fix2
#
#Revision 1.39  2007/04/19 13:05:06  elmsheus
#Add threading fix
#
#Revision 1.38  2007/04/19 12:48:49  fbrochu
#removed orphan call to getDatasets()
#
#Revision 1.37  2007/04/03 07:40:07  elmsheus
#Add correct number_of_files for jobs and subjobs
#
#Revision 1.36  2007/04/02 15:51:55  elmsheus
#Fix DQ2OutputDataset.retrieve problems
#
#Revision 1.35  2007/04/02 09:55:44  elmsheus
#* Add number_of_files option in DQ2Dataset
#* Update splitting etc to new get_contents method
#
#Revision 1.34  2007/04/02 08:07:25  elmsheus
#* Fix directory scanning procedure in Athena.prepare()
#* Fix GUIPrefs problems
#
#Revision 1.33  2007/03/22 11:29:02  elmsheus
#Fix retrieve environment
#
#Revision 1.32  2007/03/21 15:11:29  elmsheus
#Add GUIPrefs
#
#Revision 1.31  2007/03/20 16:46:40  elmsheus
#Small fixes
#
#Revision 1.30  2007/03/13 13:42:41  elmsheus
#Remove match_ce and introduce match_ce_all
#
#Revision 1.29  2007/03/13 13:11:04  liko
#Add a thread lock to protect DQ2
#
#Revision 1.28  2007/03/05 09:55:00  liko
#DQ2Dataset leanup
#
#Revision 1.27  2007/02/22 12:55:41  elmsheus
#Fix output path and use gridShell
#
#Revision 1.26  2007/02/19 08:24:45  elmsheus
#Change TiersOfAtlasCache loading
#
#Revision 1.25  2007/02/12 18:14:20  elmsheus
#Register Dataset registration
#
#Revision 1.24  2007/02/12 15:31:42  elmsheus
#Port 4.2.8 changes to head
#Fix job.splitter in Athena*RTHandler
#
#Revision 1.23  2007/01/22 09:51:01  elmsheus
#* Port changes from Ganga 4.2.7 to head:
#  - Athena.py: fix bug #22129 local athena jobs on lxplus - cmt interference
#               Fix athena_compile problem
#  - ganga-stage-in-out-dq2.py, athena-lcg:
#    Revise error exit codes correpsonding to ProdSys WRAPLCG schema
#  - DQ2Dataset.py: fix logger hick-ups
#  - Add patch to access DPM SE
#
#Revision 1.22  2006/12/21 17:24:17  elmsheus
#* Remove DQ2 curl functionality
#* Introduce dq2_client library and port all calls
#* Remove curl calls and use urllib instead
#* Remove ganga-stagein-dq2.py and ganga-stageout-dq2.py and merge into
#  new ganga-stage-in-out-dq2.py
#* Move DQ2 splitting from Athena*RTHandler.py into AthenaSplitterJob
#  therefore introduce new field DQ2Dataset.guids
#* Use AthenaMC mechanism to register files in DQ2 also for Athena plugin
#  ie. all DQ2 communication is done in the Ganga UI
#
#Revision 1.21  2006/11/27 12:18:02  elmsheus
#Fix CVS merging errors
#
#Revision 1.20  2006/11/24 15:39:13  elmsheus
#Small fixes
#
#Revision 1.19  2006/11/24 13:32:37  elmsheus
#Merge changes from Ganga-4-2-2-bugfix-branch to the trunk
#Add Frederics changes and improvement for AthenaMC
#
#Revision 1.18.2.3  2006/11/23 14:50:18  elmsheus
#Fix ce bug
#
#Revision 1.18.2.2  2006/11/22 14:20:52  elmsheus
#* introduce prefix_hack to lcg-cp/lr calls in
#  ATLASOutputDataset.retrieve()
#* fixed double downloading feature in
#  ATLASOutputDataset.retrieve()
#* move download location for ATLASOutputDataset.retrieve()
#  to job.outputdir from temp directory if local_location is not given
#* Print out clear error message if cmt parsing fails in Athena.py
#* Migrate to GridProxy library in Athena*RTHandler.py
#* Changes in output renaming schema for DQ2OutputDataset files
#
#* Fix proxy name bug in AthenaMCLCGRTHandler.py
#* Fix path problem in wrapper.sh
#
#Revision 1.18.2.1  2006/11/01 07:08:49  elmsheus
#Fix bug #21234
#
#Revision 1.18  2006/10/12 15:17:32  elmsheus
#Fix for actually one DQ2 call
#
#Revision 1.17  2006/10/12 09:04:51  elmsheus
#DQ2 code clean-up
#
#Revision 1.16  2006/10/03 12:09:48  elmsheus
#Minor fix
#
#Revision 1.15  2006/10/03 11:59:54  elmsheus
#Fix bugs #20262, 20288
#
#Revision 1.14  2006/09/29 12:23:02  elmsheus
#Small fixes
#
#Revision 1.13  2006/09/26 11:19:19  elmsheus
#Frederic updates for AthenaMC
#
#Revision 1.12  2006/09/09 09:36:23  elmsheus
#Fix DQ2OutputDataset for local backend
#
#Revision 1.11  2006/09/08 16:11:44  elmsheus
#Expand SimpleItem directory variables with expandfilenames
#
#Revision 1.10  2006/08/25 18:27:24  elmsheus
#Add master job info output
#
#Revision 1.9  2006/08/14 12:40:15  elmsheus
#Fix dataset handling during job submission, add match_ce flag for DQ2Dataset, enable ATLASDataset also for Local backend
#
#Revision 1.8  2006/08/10 15:57:00  elmsheus
#Introduction of TAG analysis
#
#Revision 1.7  2006/08/09 16:47:12  elmsheus
#Introduction of DQ2OutputDataset, fix minor bugs
#
#Revision 1.6  2006/07/31 13:42:03  elmsheus
#Apdapt to framework changes
#
#Revision 1.5  2006/07/09 08:41:02  elmsheus
#ATLASOutputDataset introduction, DQ2 updates, Splitter and Merger code clean-up, and more
#
#Revision 1.3  2006/06/19 13:32:15  elmsheus
#Update to DQ2 0.2.10+
#
#Revision 1.2  2006/05/15 20:30:49  elmsheus
#* DQ2Dataset.py:
#  return contents correctly if inputdata.names are given
#  introduce: type variable, choose LFC or DQ2
#* AthenaLCGRTHandler.py, AthenaLocalRTHandler.py:
#  remove code for trailing number removal in pool.root files and insert
#  code in ganga-stagein-dq2.py and input.py (choose LFC or DQ2)
#  save filenames in inputdata.names for subjobs
#  typo ATLASDataset
#* ganga-stagein-dq2.py:
#  code for trailing number removal in pool.root files
#  choose LFC or DQ2 dataset type
#* Athena.py:
#  code for trailing number removal in pool.root files in generated
#  input.py
#
#Revision 1.1  2006/05/09 13:45:30  elmsheus
#Introduction of
# Athena job splitting based on number of subjobs
# DQ2Dataset and DQ2 file download
# AthenaLocalDataset
#
