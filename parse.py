import csv
from lxml import html
from pprint import pprint
from zipfile import ZipFile
from io import TextIOWrapper
from urllib.parse import urljoin

from zavod import PathLike, init_context, Zavod

BASE_URL = "http://download.companieshouse.gov.uk/en_output.html"
PSC_URL = "http://download.companieshouse.gov.uk/en_pscdata.html"


def get_base_data_url(context: Zavod):
    res = context.http.get(BASE_URL)
    doc = html.fromstring(res.text)
    for link in doc.findall(".//a"):
        url = urljoin(BASE_URL, link.get("href"))
        if "BasicCompanyDataAsOneFile" in url:
            return url


def read_base_data_csv(path: PathLike):
    with ZipFile(path, "r") as zip:
        for name in zip.namelist():
            with zip.open(name, "r") as fh:
                fhtext = TextIOWrapper(fh)
                for row in csv.DictReader(fhtext):
                    yield {k.strip(): v for (k, v) in row.items()}


def parse_base_data(context: Zavod):
    data_url = get_base_data_url(context)
    if data_url is None:
        context.log.error("Base data zip URL not found!")
        return
    data_path = context.fetch_resource("base_data.zip", data_url)
    for row in read_base_data_csv(data_path):
        try:
            company_nr = row.pop("CompanyNumber")
        except KeyError:
            print(row)
            break
        entity = context.make("Company")
        entity.id = context.make_slug(company_nr)
        entity.add("name", row.pop("CompanyName"))
        entity.add("registrationNumber", company_nr)
        entity.add("status", row.pop("CompanyStatus"))
        entity.add("country", row.pop("CountryOfOrigin"))
        entity.add("jurisdiction", "gb")
        entity.add("sourceUrl", row.pop("URI"))

        for i in range(1, 11):
            row.pop(f"PreviousName_{i}.CONDATE")
            entity.add("previousName", row.pop(f"PreviousName_{i}.CompanyName"))

        # print(row)
        pprint(entity.to_dict())


def get_psc_data_url(context: Zavod):
    res = context.http.get(PSC_URL)
    doc = html.fromstring(res.text)
    for link in doc.findall(".//a"):
        url = urljoin(BASE_URL, link.get("href"))
        if "persons-with-significant-control-snapshot" in url:
            return url


def read_psc_data(path: PathLike):
    with ZipFile(path, "r") as zip:
        for name in zip.namelist():
            print(name)
            # with zip.open(name, "r") as fh:
            #     fhtext = TextIOWrapper(fh)
            #     for row in csv.DictReader(fhtext):
            #         yield {k.strip(): v for (k, v) in row.items()}


def parse_psc_data(context: Zavod):
    data_url = get_psc_data_url(context)
    if data_url is None:
        context.log.error("PSC data zip URL not found!")
        return
    data_path = context.fetch_resource("psc_data.zip", data_url)
    read_psc_data(data_path)


if __name__ == "__main__":
    with init_context("gb_coh_psc", "gb-coh") as context:
        # parse_base_data(context)
        parse_psc_data(context)
