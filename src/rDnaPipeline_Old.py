#! /usr/bin/env python

import os
import logging

from pbrdna.log import initialize_logger
from pbrdna.arguments import args, parse_args
from pbrdna.io.has_ccs import file_has_ccs
from pbrdna.io.extract_ccs import extract_ccs
from pbrdna.io.MothurIO import SummaryReader
from pbrdna.fasta.utils import copy_fasta_list
from pbrdna.fastq.quality_filter import quality_filter
from pbrdna.fastq.QualityAligner import QualityAligner
from pbrdna.fastq.QualityMasker import QualityMasker
from pbrdna.mothur.MothurTools import MothurRunner
from pbrdna.cluster.ClusterSeparator import ClusterSeparator
from pbrdna.cluster.generate_consensus import generate_consensus_files
from pbrdna.cluster.select_consensus import select_consensus_files
from pbrdna.cluster.clean_consensus import clean_consensus_outputs
from pbrdna.resequence.DagConTools import DagConRunner
from pbrdna.utils import (validate_executable,
                          create_directory,
                          split_root_from_ext,
                          get_output_name,
                          file_exists,
                          all_files_exist,
                          write_dummy_file)

log = logging.getLogger()

class rDnaPipeline( object ):
    """
    A tool for running a community analysis pipeline on PacBioData
    """

    def __init__(self):
        parse_args()
        self.__dict__.update( vars(args) )
        self.validate_settings()
        self.initialize_output()
        initialize_logger( log, log_file=self.log_file, debug=self.debug )

    def validate_settings(self):
        # Validate the input file
        root, ext = split_root_from_ext( self.input_file )
        if ext in ['.bas.h5', '.fofn']:
            self.data_type = 'bash5'
        elif ext in ['.fq', '.fastq']:
            self.data_type = 'fastq'
        elif ext in ['.fa', '.fsa', '.fasta']:
            self.data_type = 'fasta'
        else:
            raise TypeError('Sequence file must be a bas.h5 file, a ' + \
                            'fasta file, or a fofn of multiple such files')
        self.consensusTool = DagConRunner('gcon.py', 'r')
        # Searching for Mothur executable, and set the Mothur Process counter
        self.mothur = validate_executable( self.mothur )
        self.processCount = 0

    def initialize_output(self):
        # Create the Output directory
        create_directory( self.output_dir )
        # Create a symbolic link from the data file to the output dir
        baseName = os.path.basename( self.input_file )
        symlinkPath = os.path.join( self.output_dir, baseName )
        if os.path.exists( symlinkPath ):
            pass
        else:
            absPath = os.path.abspath( self.input_file )
            os.symlink( absPath, symlinkPath )
        self.sequenceFile = baseName
        # Move into the Output directory and create Log directory and files
        os.chdir( self.output_dir )
        create_directory( 'log' )
        stdoutLog = os.path.join('log', 'mothur_stdout.log')
        stderrLog = os.path.join('log', 'mothur_stderr.log')
        self.log_file = os.path.join('log', 'rna_pipeline.log')
        # Instantiate the MothurRunner object
        self.factory = MothurRunner( self.mothur, 
                                     self.nproc, 
                                     stdoutLog, 
                                     stderrLog)

    def getProcessLogFile(self, process, isMothurProcess=False):
        if isMothurProcess:
            logFile = 'process%02d.mothur.%s.logfile' % (self.processCount, 
                                                         process)
        else:
            logFile = 'process%02d.%s.logfile' % (self.processCount, process)
        return os.path.join('log', logFile)

    def process_setup(self, inputFile, processName, suffix=None, suffixList=None):
        """ 
        Return a tuple containing the output file and a boolean flag describing
        whether the output file already exists
        """
        log.info('Preparing to run %s on "%s"' % (processName, inputFile))
        self.processCount += 1
        if suffix:
            outputFile = get_output_name(inputFile, suffix)
            return outputFile
        elif suffixList:
            outputFiles = []
            for suffix in suffixList:
                outputFile = get_output_name( inputFile, suffix )
                outputFiles.append( outputFile )
            return outputFiles

    def output_files_exist(self, output_file=None, output_list=None):
        if output_file:
            if file_exists( output_file ):
                log.info('Output files detected, skipping process...\n')
                return True
            else:
                log.info('Output files not found, running process...')
                return False
        elif output_list:
            if all_files_exist( output_list ):
                log.info('Output files detected, skipping process...\n')
                return True
            else:
                log.info('Output files not found, running process...')
                return False

    def check_output_file( self, outputFile ):
        if os.path.exists( outputFile ):
            log.info('Expected output "%s" found' % outputFile)
        else:
            msg = 'Expected output "%s" not found!' % outputFile
            log.error( msg )
            raise IOError( msg )

    def process_cleanup(self, output_file=None, output_list=None):
        """
        Log if the process successfully created it's output, and raise an
        error message if not
        """
        if output_file:
            self.check_output_file( output_file )
        elif output_list:
            for output_file in output_list:
                self.check_output_file( output_file )
        log.info('All expected output files found - process successful!\n')

    def extract_raw_ccs(self, inputFile):
        outputFile = self.process_setup( inputFile, 
                                         'extractCcsFromBasH5',
                                         suffix='fastq' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        elif file_has_ccs( inputFile ):
            extract_ccs(inputFile, outputFile, self.raw_data)
        else:
            msg = 'Raw data file has no CCS data!'
            log.error( msg )
            raise ValueError( msg )
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def filter_fastq(self, fastqFile):
        outputFile = self.process_setup( fastqFile, 
                                         'FilterQuality',
                                         suffix='filter.fastq' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        quality_filter( fastqFile, outputFile, min_accuracy=self.min_accuracy )
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def separate_fastq(self, fastqFile):
        outputList = self.process_setup( fastqFile, 
                                        'Fastq.Info', 
                                        suffixList=['fasta', 'qual'] )
        if self.output_files_exist(output_list=outputList):
            return outputList
        mothurArgs = {'fastq':fastqFile, 'fasta':'T', 'qfile':'T'}
        logFile = self.getProcessLogFile('fastq.info', True)
        self.factory.runJob('fastq.info', mothurArgs, logFile)
        self.process_cleanup(output_list=outputList)
        return outputList

    def align_sequences(self, fastaFile):
        outputFile = self.process_setup( fastaFile, 
                                        'Align.Seqs', 
                                        suffix='align' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        mothurArgs = {'fasta':fastaFile,
                      'reference':self.alignment_reference,
                      'flip':'t'}
        logFile = self.getProcessLogFile('align.seqs', True)
        self.factory.runJob('align.seqs', mothurArgs, logFile)
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def screen_sequences(self, alignFile, start=None, end=None, min_length=None):
        if alignFile.endswith('.align'):
            outputExt = 'good.align'
        elif alignFile.endswith('.fasta'):
            outputExt = 'good.fasta'
        outputFile = self.process_setup( alignFile, 
                                         'Screen.Seqs', 
                                         suffix=outputExt )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        mothurArgs = {'fasta':alignFile,
                      'start':start,
                      'end':end,
                      'minlength':min_length}
        logFile = self.getProcessLogFile('screen.seqs', True)
        self.factory.runJob('screen.seqs', mothurArgs, logFile)
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def summarize_sequences(self, fastaFile):
        outputFile = self.process_setup( fastaFile, 
                                        'Summary.Seqs', 
                                        suffix='summary' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        mothurArgs = {'fasta':fastaFile}
        logFile = self.getProcessLogFile('summary.seqs', True)
        self.factory.runJob('summary.seqs', mothurArgs, logFile)
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def parse_summary_file(self, summaryFile):
        log.info('Preparing to run SummaryReader...')
        parser = SummaryReader(summaryFile, self.fraction)
        log.info('Identifying full-length alignment positions...')
        start, end = parser.getFullLengthPositions()
        log.info('Full-length start is NAST Alignment position %s' % start)
        log.info('Full-length end is NAST Alignment position %s' % end)
        log.info('Calculating minimum allowed alignment positions...')
        maxStart, minEnd = parser.getAllowedPositions()
        log.info('Maximum allowed start is NAST Alignment position %s' % maxStart)
        log.info('Minimum allowed end is NAST Alignment position %s\n' % minEnd)
        return maxStart, minEnd

    def find_chimeras(self, alignFile):
        outputFile = self.process_setup( alignFile, 
                                        'UCHIME', 
                                        suffix='uchime.accnos' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        mothurArgs = {'fasta':alignFile,
                      'reference':self.chimera_reference}
        logFile = self.getProcessLogFile('chimera.uchime', True)
        self.factory.runJob('chimera.uchime', mothurArgs, logFile)
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def remove_sequences(self, alignFile, idFile):
        outputFile = self.process_setup( alignFile, 
                                        'Remove.Seqs', 
                                        suffix='pick.align' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        mothurArgs = {'fasta':alignFile,
                      'accnos':idFile}
        logFile = self.getProcessLogFile('remove.seqs', True)
        self.factory.runJob('remove.seqs', mothurArgs, logFile)
        self.process_cleanup(output_file=outputFile)
        return outputFile
  
    def filter_sequences(self, alignFile, trump=None ):
        outputFile = self.process_setup( alignFile, 
                                        'Filter.Seqs', 
                                        suffix='filter.fasta' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        mothurArgs = {'fasta': alignFile,
                      'vertical': 'T',
                      'trump': trump}
        logFile = self.getProcessLogFile( 'filter.seqs', True )
        self.factory.runJob( 'filter.seqs', mothurArgs, logFile )
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def add_quality_to_alignment(self, fastqFile, alignFile):
        outputFile = self.process_setup( alignFile, 
                                        'QualityAligner', 
                                        suffix='fastq' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        aligner = QualityAligner( fastqFile, alignFile, outputFile )
        aligner.run()
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def mask_fastq_sequences(self, fastqFile):
        outputFile = self.process_setup( fastqFile, 
                                        'QualityMasker', 
                                        suffix='masked.fastq' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        masker = QualityMasker(fastqFile, outputFile, self.minQv)
        masker.run()
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def unique_sequences( self, alignFile ):
        if alignFile.endswith('.align'):
            outputSuffixes = ['unique.align', 'names']
        elif alignFile.endswith('.fasta'):
            outputSuffixes = ['unique.fasta', 'names']
        outputList = self.process_setup( alignFile,
                                        'Unique.Seqs',
                                        suffixList=outputSuffixes )
        if self.output_files_exist(output_list=outputList):
            return outputList
        mothurArgs = {'fasta':alignFile}
        logFile = self.getProcessLogFile('unique.seqs', True)
        self.factory.runJob('unique.seqs', mothurArgs, logFile)
        self.process_cleanup(output_list=outputList)
        return outputList

    def precluster_sequences( self, alignFile, nameFile ):
        if alignFile.endswith('.align'):
            outputSuffixes = ['precluster.align', 'precluster.names']
        elif alignFile.endswith('.fasta'):
            outputSuffixes = ['precluster.fasta', 'precluster.names']
        outputList = self.process_setup( alignFile,
                                        'Pre.Cluster',
                                        suffixList=outputSuffixes )
        if self.output_files_exist(output_list=outputList):
            return outputList
        mothurArgs = { 'fasta':alignFile,
                       'name': nameFile,
                       'diffs':self.precluster_diffs }
        logFile = self.getProcessLogFile('pre.cluster', True)
        self.factory.runJob('pre.cluster', mothurArgs, logFile)
        self.process_cleanup(output_list=outputList)
        return outputList

    def calculate_distance_matrix( self, alignFile ):
        outputFile = self.process_setup( alignFile, 
                                        'Dist.Seqs', 
                                        suffix='phylip.dist' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        mothurArgs = { 'fasta':alignFile,
                       'calc':'onegap',
                       'countends':'F',
                       'output':'lt' }
        logFile = self.getProcessLogFile('dist.seqs', True)
        self.factory.runJob('dist.seqs', mothurArgs, logFile)
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def cluster_sequences(self, distanceMatrix, nameFile):
        if self.clusteringMethod == 'nearest':
            outputSuffix = 'nn.list'
        elif self.clusteringMethod == 'average':
            outputSuffix = 'an.list'
        elif self.clusteringMethod == 'furthest':
            outputSuffix = 'fn.list'
        outputFile = self.process_setup( distanceMatrix, 
                                        'Cluster', 
                                        suffix=outputSuffix )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        mothurArgs = {'phylip':distanceMatrix,
                      'name':nameFile,
                      'method':self.clusteringMethod}
        logFile = self.getProcessLogFile( 'cluster', True )
        self.factory.runJob( 'cluster', mothurArgs, logFile )
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def separate_cluster_sequences(self, listFile, sequenceFile):
        outputFile = self.process_setup( listFile, 
                                        'ClusterSeparator', 
                                        suffix='list.clusters')
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        separator = ClusterSeparator( listFile, 
                                      sequenceFile,
                                      outputFile,
                                      self.distance, 
                                      self.min_cluster_size )
        separator()
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def generate_consensus_sequences(self, cluster_list_file):
        output_file = self.process_setup( cluster_list_file,
                                        'ClusterResequencer', 
                                        suffix='consensus')
        if self.output_files_exist(output_file=output_file):
            return output_file
        generate_consensus_files( cluster_list_file, self.consensusTool, output_file )
        self.process_cleanup(output_file=output_file)
        return output_file

    def cleanup_uchime_output( self, screenedFile ):
        outputFile = self.process_setup( screenedFile,
                                         'UchimeCleanup',
                                         suffix='uchime.cleanup' )
        uchimePath = os.getcwd()
        for filename in os.listdir( uchimePath ):
            if filename.endswith('_formatted'):
                file_path = os.path.join( uchimePath, filename )
                os.remove( file_path )
        write_dummy_file( outputFile )
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def cleanup_consensus_folder( self, consensusFile ):
        outputFile = self.process_setup( consensusFile, 
                                        'ConsensusCleanup', 
                                        suffix='consensus.cleanup' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        reseqPath = os.path.join( os.getcwd(), 'reseq' )
        clean_consensus_outputs( reseqPath, outputFile )
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def select_final_sequences( self, consensusFile ):
        outputFile = self.process_setup( consensusFile,
                                        'SequenceSelector', 
                                        suffix='consensus.selected' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        select_consensus_files( consensusFile, outputFile )
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def output_final_sequences( self, finalSequenceList ):
        outputFile = self.process_setup( finalSequenceList, 
                                        'SequenceWriter',
                                        suffix='fasta' )
        if self.output_files_exist(output_file=outputFile):
            return outputFile
        copy_fasta_list( finalSequenceList, outputFile )
        self.process_cleanup(output_file=outputFile)
        return outputFile

    def run(self):
        if self.data_type == 'bash5':
            fastqFile = self.extract_raw_ccs( self.sequenceFile )
        elif self.data_type == 'fastq':
            fastqFile = self.sequenceFile
        elif self.data_type == 'fasta':
            fastqFile = None
            fastaFile = self.sequenceFile

        # If we have a Fastq, filter low-quality reads and convert to FASTA
        if fastqFile:
            filteredFastq = self.filter_fastq( fastqFile )
            fastaFile, qualFile = self.separate_fastq( filteredFastq )

        # Align the Fasta sequences and remove partial reads
        alignedFile = self.align_sequences( fastaFile )
        summaryFile = self.summarize_sequences( alignedFile )
        maxStart, minEnd = self.parse_summary_file( summaryFile )
        screenedFile = self.screen_sequences(alignedFile,
                                             start=maxStart,
                                             end=minEnd)

        # Identify and remove chimeric reads
        chimera_ids = self.find_chimeras( screenedFile )
        self.cleanup_uchime_output( screenedFile )
        if file_exists( chimera_ids ):
            no_chimera_file = self.remove_sequences( screenedFile, chimera_ids )
        else:
            no_chimera_file = screenedFile

        # Filter out un-used columns to speed up re-alignment and clustering
        filteredFile = self.filter_sequences( no_chimera_file, trump='.' )

        uniqueFile, nameFile = self.unique_sequences( filteredFile )
        preclusteredFile, nameFile = self.precluster_sequences( uniqueFile, nameFile )
        fileForClustering = preclusteredFile

        distanceMatrix = self.calculate_distance_matrix( fileForClustering )
        listFile = self.cluster_sequences( distanceMatrix, nameFile )

        clusterListFile = self.separate_cluster_sequences( listFile, fastqFile )
        consensusFile = self.generate_consensus_sequences( clusterListFile )
        self.cleanup_consensus_folder( consensusFile )
        selectedFile = self.select_final_sequences( consensusFile )
        finalFile = self.output_final_sequences( selectedFile )

if __name__ == '__main__':
    rDnaPipeline().run()
