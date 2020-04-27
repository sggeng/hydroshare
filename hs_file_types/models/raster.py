import os
import logging
import shutil
import subprocess
import zipfile
from urllib.parse import quote

import xml.etree.ElementTree as ET
from lxml import etree

import gdal
from gdalconst import GA_ReadOnly

from functools import partial, wraps

from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms.models import formset_factory
from django.template import Template, Context

from dominate.tags import div, legend, form, button, table, tbody, tr, th, td, a, span, i, p

from hs_core.hydroshare import utils
from hs_core.forms import CoverageTemporalForm, CoverageSpatialForm
from hs_core.models import ResourceFile, CoreMetaData
from hs_core.signals import post_add_raster_aggregation

from hs_geo_raster_resource.models import CellInformation, BandInformation, OriginalCoverage, \
    GeoRasterMetaDataMixin
from hs_geo_raster_resource.forms import BandInfoForm, BaseBandInfoFormSet, BandInfoValidationForm

from hs_file_types import raster_meta_extract
from .base import AbstractFileMetaData, AbstractLogicalFile, FileTypeContext


class GeoRasterFileMetaData(GeoRasterMetaDataMixin, AbstractFileMetaData):
    # the metadata element models used for this file type are from the raster resource type app
    # use the 'model_app_label' attribute with ContentType, do dynamically find the right element
    # model class from element name (string)
    model_app_label = 'hs_geo_raster_resource'

    @classmethod
    def get_metadata_model_classes(cls):
        metadata_model_classes = super(GeoRasterFileMetaData, cls).get_metadata_model_classes()
        metadata_model_classes['originalcoverage'] = OriginalCoverage
        metadata_model_classes['bandinformation'] = BandInformation
        metadata_model_classes['cellinformation'] = CellInformation
        return metadata_model_classes

    def get_metadata_elements(self):
        elements = super(GeoRasterFileMetaData, self).get_metadata_elements()
        elements += [self.cellInformation, self.originalCoverage]
        elements += list(self.bandInformations.all())
        return elements

    def get_html(self):
        """overrides the base class function to generate html needed to display metadata
        in view mode"""

        html_string = super(GeoRasterFileMetaData, self).get_html()
        if self.spatial_coverage:
            html_string += self.spatial_coverage.get_html()
        if self.originalCoverage:
            html_string += self.originalCoverage.get_html()

        html_string += self.cellInformation.get_html()
        if self.temporal_coverage:
            html_string += self.temporal_coverage.get_html()
        band_legend = legend("Band Information")
        html_string += band_legend.render()
        for band_info in self.bandInformations:
            html_string += band_info.get_html()
        html_string += self._get_data_services_html()

        template = Template(html_string)
        context = Context({})
        return template.render(context)

    def _getGeoServerServiceURL(self, service):
        resId = 'fa3c985723ff45bdbf8cb18321d2df3e' 
        return (
            f'{settings.HS_GEOSERVER}/HS={resId}/'
            f'{service}?request=GetCapabilities&service={service.upper()}'
        )

    def _getPreviewDataURL(self, service):
        # We need to URI encode each part of the URL

        # TODO: access resource id
        resId = quote('fa3c985723ff45bdbf8cb18321d2df3e')
        
        extent = str(self.spatial_coverage.value['westlimit']) \
        + "," + str(self.spatial_coverage.value['southlimit']) \
        + "," + str(self.spatial_coverage.value['eastlimit']) \
        + "," + str(self.spatial_coverage.value['northlimit'])
        datasetName = quote(self.logical_file.dataset_name.encode("utf-8"))
        width = 800
        height = 600
        
        # Get the last 9 characters of the string to parse the EPSG string
        # i.e: 'WGS 84 EPSG:4326' => 'EPSG:4326'
        srs=quote(self.spatial_coverage.value['projection'][-9:])

        return (
            f'{settings.HS_GEOSERVER}/HS={resId}/'
            f'{service}?service={service.upper()}'
            f'&version=1.1.0&request=GetMap&layers={resId}:{datasetName}'
            f'&bbox={extent}'
            f'&width={width}&height={height}&srs={srs}'
            f'&format=application/openlayers'
        )

    def _get_data_services_html(self):
        root_div = div(cls="content-block")
        with root_div:
            legend('Data Services')
            with table(cls='info-table'):
                with tbody():
                    with tr(cls='row'):
                        with th():
                            a('Web Mapping Service (WMS)', href=self._getGeoServerServiceURL('wms'), 
                            target='_blank')
                            span(self._getGeoServerServiceURL('wms'), 
                            id='link-wms', style='display: none;')
                        with td():
                            with button(type='button', cls='btn btn-default clipboard-copy', 
                            data_target='link-wms', style='border-radius: 4px;'):
                                i(cls='fa fa-clipboard')
                                span('Copy Service URL')
                    with tr(cls='row'):
                        with th():
                            a('Web Coverage Service (WCS)', href=self._getGeoServerServiceURL('wcs'), 
                            target='_blank')
                            span(self._getGeoServerServiceURL('wcs'), id='link-wcs', style='display: none;')
                        with td():
                            with button(type='button', cls='btn btn-default clipboard-copy', 
                            data_target='link-wcs', style='border-radius: 4px;'):
                                i(cls='fa fa-clipboard')
                                span('Copy Service URL')
            a('Preview Data', cls='btn btn-primary', href=self._getPreviewDataURL('wms'), target='_blank')
            with p(cls='space-top'):
                span('Please refer to ') 
                a("HydroShare's Help documentation", href='https://help.hydroshare.org/', target='_blank')
                span(' for examples of how to use these services')

        return root_div.render()

    def get_html_forms(self, dataset_name_form=True, temporal_coverage=True, **kwargs):
        """overrides the base class function to generate html needed for metadata editing"""

        root_div = div("{% load crispy_forms_tags %}")
        with root_div:
            super(GeoRasterFileMetaData, self).get_html_forms()
            with div(id="spatial-coverage-filetype"):
                with form(id="id-spatial-coverage-file-type",
                          cls='hs-coordinates-picker', data_coordinates_type="point",
                          action="{{ coverage_form.action }}",
                          method="post", enctype="multipart/form-data"):
                    div("{% crispy coverage_form %}")
                    with div(cls="row", style="margin-top:10px;"):
                        with div(cls="col-md-offset-10 col-xs-offset-6 "
                                     "col-md-2 col-xs-6"):
                            button("Save changes", type="button",
                                   cls="btn btn-primary pull-right",
                                   style="display: none;")

                div("{% crispy orig_coverage_form %}", cls="content-block")

                div("{% crispy cellinfo_form %}", cls='content-block')

                with div(id="variables", cls="content-block"):
                    div("{% for form in bandinfo_formset_forms %}")
                    with form(id="{{ form.form_id }}", action="{{ form.action }}",
                              method="post", enctype="multipart/form-data", cls='well'):
                        div("{% crispy form %}")
                        with div(cls="row", style="margin-top:10px;"):
                            with div(cls="col-md-offset-10 col-xs-offset-6 "
                                         "col-md-2 col-xs-6"):
                                button("Save changes", type="button",
                                       cls="btn btn-primary pull-right btn-form-submit",
                                       style="display: none;")
                    div("{% endfor %}")

        template = Template(root_div.render())
        context_dict = dict()

        context_dict["orig_coverage_form"] = self.get_original_coverage_form()
        context_dict["cellinfo_form"] = self.get_cellinfo_form()
        temp_cov_form = self.get_temporal_coverage_form()

        update_action = "/hsapi/_internal/GeoRasterLogicalFile/{0}/{1}/{2}/update-file-metadata/"
        create_action = "/hsapi/_internal/GeoRasterLogicalFile/{0}/{1}/add-file-metadata/"
        spatial_cov_form = self.get_spatial_coverage_form(allow_edit=True)
        if self.spatial_coverage:
            form_action = update_action.format(self.logical_file.id, "coverage",
                                               self.spatial_coverage.id)
        else:
            form_action = create_action.format(self.logical_file.id, "coverage")

        spatial_cov_form.action = form_action

        if self.temporal_coverage:
            form_action = update_action.format(self.logical_file.id, "coverage",
                                               self.temporal_coverage.id)
            temp_cov_form.action = form_action
        else:
            form_action = create_action.format(self.logical_file.id, "coverage")
            temp_cov_form.action = form_action

        context_dict["coverage_form"] = spatial_cov_form
        context_dict["temp_form"] = temp_cov_form
        context_dict["bandinfo_formset_forms"] = self.get_bandinfo_formset().forms
        context = Context(context_dict)
        rendered_html = template.render(context)
        return rendered_html

    def get_cellinfo_form(self):
        return self.cellInformation.get_html_form(resource=None)

    def get_original_coverage_form(self):
        return OriginalCoverage.get_html_form(resource=None, element=self.originalCoverage,
                                              file_type=True, allow_edit=False)

    def get_bandinfo_formset(self):
        BandInfoFormSetEdit = formset_factory(
            wraps(BandInfoForm)(partial(BandInfoForm, allow_edit=True)),
            formset=BaseBandInfoFormSet, extra=0)
        bandinfo_formset = BandInfoFormSetEdit(
            initial=list(self.bandInformations.values()), prefix='BandInformation')

        for frm in bandinfo_formset.forms:
            if len(frm.initial) > 0:
                frm.action = "/hsapi/_internal/%s/%s/bandinformation/%s/update-file-metadata/" % (
                    "GeoRasterLogicalFile", self.logical_file.id, frm.initial['id'])
                frm.number = frm.initial['id']

        return bandinfo_formset

    @classmethod
    def validate_element_data(cls, request, element_name):
        """overriding the base class method"""

        if element_name.lower() not in [el_name.lower() for el_name
                                        in cls.get_supported_element_names()]:
            err_msg = "{} is nor a supported metadata element for Geo Raster file type"
            err_msg = err_msg.format(element_name)
            return {'is_valid': False, 'element_data_dict': None, "errors": err_msg}
        element_name = element_name.lower()
        if element_name == 'bandinformation':
            form_data = {}
            for field_name in BandInfoValidationForm().fields:
                matching_key = [key for key in request.POST if '-' + field_name in key][0]
                form_data[field_name] = request.POST[matching_key]
            element_form = BandInfoValidationForm(form_data)
        elif element_name == 'coverage' and 'start' not in request.POST:
            element_form = CoverageSpatialForm(data=request.POST)
        else:
            # element_name must be coverage
            # here we are assuming temporal coverage
            element_form = CoverageTemporalForm(data=request.POST)

        if element_form.is_valid():
            return {'is_valid': True, 'element_data_dict': element_form.cleaned_data}
        else:
            return {'is_valid': False, 'element_data_dict': None, "errors": element_form.errors}

    def get_xml(self, pretty_print=True):
        """Generates ORI+RDF xml for this aggregation metadata"""

        # get the xml root element and the xml element to which contains all other elements
        RDF_ROOT, container_to_add_to = super(GeoRasterFileMetaData, self)._get_xml_containers()

        if self.originalCoverage:
            self.originalCoverage.add_to_xml_container(container_to_add_to)
        if self.cellInformation:
            self.cellInformation.add_to_xml_container(container_to_add_to)
        for bandinfo in self.bandInformations:
            bandinfo.add_to_xml_container(container_to_add_to)

        return CoreMetaData.XML_HEADER + '\n' + etree.tostring(RDF_ROOT, encoding='UTF-8',
                                                               pretty_print=pretty_print).decode()


class GeoRasterLogicalFile(AbstractLogicalFile):
    metadata = models.OneToOneField(GeoRasterFileMetaData, related_name="logical_file")
    data_type = "GeographicRaster"

    @classmethod
    def get_allowed_uploaded_file_types(cls):
        """only .zip and .tif file can be set to this logical file group"""
        return [".zip", ".tif", ".tiff"]

    @classmethod
    def get_main_file_type(cls):
        """The main file type for this aggregation"""
        return ".vrt"

    @classmethod
    def get_allowed_storage_file_types(cls):
        """file types allowed in this logical file group are: .tif and .vrt"""
        return [".tiff", ".tif", ".vrt"]

    @staticmethod
    def get_aggregation_display_name():
        return 'Geographic Raster Content: A geographic grid represented by a virtual raster ' \
               'tile (.vrt) file and one or more geotiff (.tif) files'

    @staticmethod
    def get_aggregation_type_name():
        return "GeographicRasterAggregation"

    # used in discovery faceting to aggregate native and composite content types
    @staticmethod
    def get_discovery_content_type():
        """Return a human-readable content type for discovery.
        This must agree between Composite Types and native types.
        """
        return "Geographic Raster"

    @classmethod
    def create(cls, resource):
        """this custom method MUST be used to create an instance of this class"""
        raster_metadata = GeoRasterFileMetaData.objects.create(keywords=[])
        # Note we are not creating the logical file record in DB at this point
        # the caller must save this to DB
        return cls(metadata=raster_metadata, resource=resource)

    @property
    def supports_resource_file_move(self):
        """resource files that are part of this logical file can't be moved"""
        return False

    @property
    def supports_resource_file_add(self):
        """doesn't allow a resource file to be added"""
        return False

    @property
    def supports_resource_file_rename(self):
        """resource files that are part of this logical file can't be renamed"""
        return False

    @property
    def supports_delete_folder_on_zip(self):
        """does not allow the original folder to be deleted upon zipping of that folder"""
        return False

    @classmethod
    def check_files_for_aggregation_type(cls, files):
        """Checks if the specified files can be used to set this aggregation type
        :param  files: a list of ResourceFile objects

        :return If the files meet the requirements of this aggregation type, then returns this
        aggregation class name, otherwise empty string.
        """
        if not files:
            # no files
            return ""

        for fl in files:
            if fl.extension.lower() not in cls.get_allowed_storage_file_types():
                return ""

        # check that there can be only one vrt file
        vrt_files = [f for f in files if f.extension.lower() == ".vrt"]
        if len(vrt_files) > 1:
            return ""

        # check if there are multiple tif files, then there has to be one vrt file
        tif_files = [f for f in files if f.extension.lower() == ".tif" or f.extension.lower() ==
                     ".tiff"]
        if len(tif_files) > 1:
            if len(vrt_files) != 1:
                return ""
        elif not tif_files:
            # there has to be at least one tif file
            return ""

        return cls.__name__

    @classmethod
    def set_file_type(cls, resource, user, file_id=None, folder_path=None):
        """ Creates a GeoRasterLogicalFile (aggregation) from a tif or a zip resource file """

        log = logging.getLogger()
        with FileTypeContext(aggr_cls=cls, user=user, resource=resource, file_id=file_id,
                             folder_path=folder_path,
                             post_aggr_signal=post_add_raster_aggregation,
                             is_temp_file=True) as ft_ctx:

            res_file = ft_ctx.res_file
            file_name = res_file.file_name
            # get file name without the extension - needed for naming the aggregation folder
            base_file_name = file_name[:-len(res_file.extension)]
            file_folder = res_file.file_folder
            upload_folder = file_folder
            temp_file = ft_ctx.temp_file
            temp_dir = ft_ctx.temp_dir

            raster_folder = folder_path if folder_path is not None else file_folder
            # validate the file
            validation_results = raster_file_validation(raster_file=temp_file, resource=resource,
                                                        raster_folder=raster_folder)

            if not validation_results['error_info']:
                msg = "Geographic raster aggregation. Error when creating aggregation. Error:{}"
                file_type_success = False
                log.info("Geographic raster aggregation validation successful.")
                # extract metadata
                temp_vrt_file_path = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if
                                      '.vrt' == os.path.splitext(f)[1]].pop()
                metadata = extract_metadata(temp_vrt_file_path)
                log.info("Geographic raster metadata extraction was successful.")

                with transaction.atomic():
                    try:
                        res_files = validation_results['raster_resource_files']
                        files_to_upload = validation_results['new_resource_files_to_add']
                        # create a raster aggregation
                        logical_file = cls.create_aggregation(dataset_name=base_file_name,
                                                              resource=resource,
                                                              res_files=res_files,
                                                              new_files_to_upload=files_to_upload,
                                                              folder_path=upload_folder)

                        log.info("Geographic raster aggregation type - new files were added "
                                 "to the resource.")

                        # use the extracted metadata to populate file metadata
                        for element in metadata:
                            # here k is the name of the element
                            # v is a dict of all element attributes/field names and field values
                            k, v = list(element.items())[0]
                            logical_file.metadata.create_element(k, **v)
                        log.info("Geographic raster aggregation type - metadata was saved to DB")

                        file_type_success = True
                        ft_ctx.logical_file = logical_file
                    except Exception as ex:
                        msg = msg.format(str(ex))
                        log.exception(msg)

                if not file_type_success:
                    raise ValidationError(msg)
            else:
                err_msg = "Geographic raster aggregation type validation failed. {}".format(
                    ' '.join(validation_results['error_info']))
                log.error(err_msg)
                raise ValidationError(err_msg)

    @classmethod
    def get_primary_resouce_file(cls, resource_files):
        """Gets a resource file that has extension .vrt (if exists) otherwsie 'tif'
        from the list of files *resource_files* """

        res_files = [f for f in resource_files if f.extension.lower() == '.vrt']
        if not res_files:
            res_files = [f for f in resource_files if f.extension.lower() in ('.tif', 'tiff')]

        return res_files[0] if res_files else None

    def create_aggregation_xml_documents(self, create_map_xml=True):
        super(GeoRasterLogicalFile, self).create_aggregation_xml_documents(create_map_xml)
        self.metadata.is_dirty = False
        self.metadata.save()


def raster_file_validation(raster_file, resource, raster_folder=None):
    """ Validates if the relevant files are valid for raster aggregation or raster resource type

    :param  raster_file: a temp file (extension tif or zip) retrieved from irods and stored on temp
    dir in django
    :param  raster_folder: (optional) folder in which raster file exists on irods.
    :param  resource: an instance of CompositeResource or GeoRasterResource in which
    raster_file exits.

    :return A list of error messages and a list of file paths for all files that belong to raster
    """
    error_info = []
    new_resource_files_to_add = []
    raster_resource_files = []
    create_vrt = True
    validation_results = {'error_info': error_info,
                          'new_resource_files_to_add': new_resource_files_to_add,
                          'raster_resource_files': raster_resource_files,
                          'vrt_created': create_vrt}
    file_name_part, ext = os.path.splitext(os.path.basename(raster_file))
    ext = ext.lower()
    if ext == '.tif' or ext == '.tiff':
        res_files = ResourceFile.list_folder(resource=resource, folder=raster_folder,
                                             sub_folders=False)
        if resource.resource_type == "RasterResource":
            # check if there is already a vrt file in that folder
            vrt_files = [f for f in res_files if f.extension.lower() == ".vrt"]
            tif_files = [f for f in res_files if f.extension.lower() == ".tif" or
                         f.extension.lower() == ".tiff"]
            if vrt_files:
                if len(vrt_files) > 1:
                    error_info.append("More than one vrt file was found.")
                    return validation_results
                create_vrt = False
            elif len(tif_files) != 1:
                # if there are more than one tif file, there needs to be one vrt file
                error_info.append("A vrt file is missing.")
                return validation_results

        vrt_files_for_raster = get_vrt_files(raster_file, res_files)
        if len(vrt_files_for_raster) > 1:
            error_info.append("The raster {} is listed by more than one vrt file {}".format(raster_file,
                                                                                            vrt_files_for_raster))
            return validation_results

        if len(vrt_files_for_raster) == 1:
            vrt_file = vrt_files_for_raster[0]
            raster_resource_files.extend([vrt_file])
            create_vrt = False
            temp_dir = os.path.dirname(raster_file)
            temp_vrt_file = utils.get_file_from_irods(vrt_file, temp_dir)
            listed_tif_files = list_tif_files(vrt_file)
            tif_files = [f for f in res_files if f.file_name in listed_tif_files]
            if len(tif_files) != len(listed_tif_files):
                error_info.append("The vrt file {} lists {} files, only found {}".format(vrt_file,
                                                                                         len(listed_tif_files),
                                                                                         len(tif_files)))
                return validation_results
        else:
            # create the .vrt file
            tif_files = [f for f in res_files if f.file_name == os.path.basename(raster_file)]
            try:
                vrt_file = create_vrt_file(raster_file)
                temp_vrt_file = vrt_file
            except Exception as ex:
                error_info.append(str(ex))
            else:
                if os.path.isfile(vrt_file):
                    new_resource_files_to_add.append(vrt_file)

        raster_resource_files.extend(tif_files)

    elif ext == '.zip':
        try:
            extract_file_paths = _explode_raster_zip_file(raster_file)
        except Exception as ex:
            error_info.append(str(ex))
        else:
            if extract_file_paths:
                new_resource_files_to_add.extend(extract_file_paths)
    else:
        error_info.append("Invalid file mime type found.")

    if not error_info:
        if ext == ".zip":
            # in case of zip, there needs to be more than one file extracted out of the zip file
            if len(new_resource_files_to_add) < 2:
                error_info.append("Invalid zip file. Seems to contain only one file. "
                                  "Multiple tif files are expected.")
                return validation_results

            files_ext = [os.path.splitext(path)[1].lower() for path in new_resource_files_to_add]
            if files_ext.count('.vrt') > 1:
                error_info.append("Invalid zip file. Seems to contain multiple vrt files.")
                return validation_results
            elif files_ext.count('.vrt') == 0:
                error_info.append("Invalid zip file. No vrt file was found.")
                return validation_results
            elif files_ext.count('.tif') + files_ext.count('.tiff') < 1:
                error_info.append("Invalid zip file. No tif/tiff file was found.")
                return validation_results

            # check if there are files that are not raster related
            non_raster_files = [f_ext for f_ext in files_ext if f_ext
                                not in ('.tif', '.tiff', '.vrt')]
            if non_raster_files:
                error_info.append("Invalid zip file. Contains files that are not raster related.")
                return validation_results

            temp_vrt_file = new_resource_files_to_add[files_ext.index('.vrt')]

        # validate vrt file if we didn't create it
        if ext == '.zip' or not create_vrt:
            raster_dataset = gdal.Open(temp_vrt_file, GA_ReadOnly)
            if raster_dataset is None:
                error_info.append('Failed to open the vrt file.')
                return validation_results

            # check if the vrt file is valid
            try:
                raster_dataset.RasterXSize
                raster_dataset.RasterYSize
                raster_dataset.RasterCount
            except AttributeError:
                error_info.append('Raster size and band information are missing.')
                return validation_results

            # check if the raster file numbers and names are valid in vrt file
            with open(temp_vrt_file, 'r') as vrt_file:
                vrt_string = vrt_file.read()
                root = ET.fromstring(vrt_string)
                file_names_in_vrt = [file_name.text for file_name in root.iter('SourceFilename')]

            if ext == '.zip':
                file_names = [os.path.basename(path) for path in new_resource_files_to_add]
            else:
                file_names = [f.file_name for f in raster_resource_files]

            file_names = [f_name for f_name in file_names if not f_name.endswith('.vrt')]

            if resource.resource_type == "RasterResource":
                tif_files = [f for f in resource.files.all() if f.extension.lower() == ".tif" or
                             f.extension.lower() == ".tiff"]
                if len(tif_files) > len(file_names_in_vrt):
                    msg = 'One or more additional tif files were found which are not listed in ' \
                          'the provided {} file.'
                    msg = msg.format(os.path.basename(temp_vrt_file))
                    error_info.append(msg)

            for vrt_ref_raster_name in file_names_in_vrt:
                if vrt_ref_raster_name in file_names \
                        or (os.path.split(vrt_ref_raster_name)[0] == '.' and
                            os.path.split(vrt_ref_raster_name)[1] in file_names):
                    continue
                elif resource.resource_type == "RasterResource" and os.path.basename(vrt_ref_raster_name) in file_names:
                    msg = "Please specify {} as {} in the .vrt file, because it will " \
                          "be saved in the same folder with .vrt file in HydroShare."
                    msg = msg.format(vrt_ref_raster_name, os.path.basename(vrt_ref_raster_name))
                    error_info.append(msg)
                    break
                else:
                    msg = "The file {tif} which is listed in the {vrt} file is missing."
                    msg = msg.format(tif=os.path.basename(vrt_ref_raster_name),
                                     vrt=os.path.basename(temp_vrt_file))
                    error_info.append(msg)
                    break

    return validation_results


def list_tif_files(vrt_file):
    """
    lists tif files named in a vrt_file
    :param vrt_file: ResourceFile for of a vrt to list associated tif(f) files
    :return: List of string filenames read from vrt_file, empty list if not found
    """
    temp_vrt_file = utils.get_file_from_irods(vrt_file)
    with open(temp_vrt_file, 'r') as opened_vrt_file:
        vrt_string = opened_vrt_file.read()
        root = ET.fromstring(vrt_string)
        file_names_in_vrt = [file_name.text for file_name in root.iter('SourceFilename')]
        return file_names_in_vrt
    return []


def get_vrt_files(raster_file, res_files):
    """
    Searches for vrt_files that lists the supplied raster_file
    :param raster_file: The raster file to find the associated vrt_file of
    :param res_files: list of ResourceFiles in the the folder of raster_file
    :return: A list of vrt ResourceFile(s) which lists the raster_file, empty List if not found.
    """
    vrt_files = [f for f in res_files if f.extension.lower() == ".vrt"]
    vrt_files_for_raster = []
    if vrt_files:
        for vrt_file in vrt_files:
            file_names_in_vrt = list_tif_files(vrt_file)
            for vrt_ref_raster_name in file_names_in_vrt:
                if raster_file.endswith(vrt_ref_raster_name):
                    vrt_files_for_raster.append(vrt_file)
    return vrt_files_for_raster


def extract_metadata(temp_vrt_file_path):
    metadata = []
    res_md_dict = raster_meta_extract.get_raster_meta_dict(temp_vrt_file_path)
    wgs_cov_info = res_md_dict['spatial_coverage_info']['wgs84_coverage_info']
    # add core metadata coverage - box
    if wgs_cov_info:
        box = {'coverage': {'type': 'box', 'value': wgs_cov_info}}
        metadata.append(box)

    # Save extended meta spatial reference
    orig_cov_info = res_md_dict['spatial_coverage_info']['original_coverage_info']

    # Here the assumption is that if there is no value for the 'northlimit' then there is no value
    # for the bounding box
    if orig_cov_info['northlimit'] is not None:
        ori_cov = {'OriginalCoverage': {'value': orig_cov_info}}
        metadata.append(ori_cov)

    # Save extended meta cell info
    res_md_dict['cell_info']['name'] = os.path.basename(temp_vrt_file_path)
    metadata.append({'CellInformation': res_md_dict['cell_info']})

    # Save extended meta band info
    for band_info in list(res_md_dict['band_info'].values()):
        metadata.append({'BandInformation': band_info})
    return metadata


def create_vrt_file(tif_file):
    """ tif_file exists in temp directory - retrieved from irods """

    log = logging.getLogger()

    # create vrt file
    temp_dir = os.path.dirname(tif_file)
    tif_file_name = os.path.basename(tif_file)
    vrt_file_path = os.path.join(temp_dir, os.path.splitext(tif_file_name)[0] + '.vrt')

    with open(os.devnull, 'w') as fp:
        subprocess.Popen(['gdal_translate', '-of', 'VRT', tif_file, vrt_file_path],
                         stdout=fp,
                         stderr=fp).wait()  # need to wait

    # edit VRT contents
    try:
        tree = ET.parse(vrt_file_path)
        root = tree.getroot()
        for element in root.iter('SourceFilename'):
            element.text = tif_file_name
            element.attrib['relativeToVRT'] = '1'

        tree.write(vrt_file_path)

    except Exception as ex:
        log.exception("Failed to create/write to vrt file. Error:{}".format(str(ex)))
        raise Exception("Failed to create/write to vrt file")

    return vrt_file_path


def _explode_raster_zip_file(zip_file):
    """ zip_file exists in temp directory - retrieved from irods """

    log = logging.getLogger()
    temp_dir = os.path.dirname(zip_file)
    try:
        zf = zipfile.ZipFile(zip_file, 'r')
        zf.extractall(temp_dir)
        zf.close()

        # get all the file abs names in temp_dir
        extract_file_paths = []
        for dirpath, _, filenames in os.walk(temp_dir):
            for name in filenames:
                file_path = os.path.abspath(os.path.join(dirpath, name))
                file_ext = os.path.splitext(os.path.basename(file_path))[1]
                file_ext = file_ext.lower()
                if file_ext in GeoRasterLogicalFile.get_allowed_storage_file_types():
                    shutil.move(file_path, os.path.join(temp_dir, name))
                    extract_file_paths.append(os.path.join(temp_dir, os.path.basename(file_path)))

    except Exception as ex:
        log.exception("Failed to unzip. Error:{}".format(str(ex)))
        raise ex

    return extract_file_paths
