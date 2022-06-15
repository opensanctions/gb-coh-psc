from concurrent.futures import ThreadPoolExecutor, wait
import csv
from functools import cache
import json
from lxml import html
from pprint import pprint
from zipfile import ZipFile
from io import TextIOWrapper
from datetime import datetime
from urllib.parse import urljoin

from zavod import PathLike, init_context, Zavod
from zavod.store import write_entity
from zavod.parse import make_address

BASE_URL = "http://download.companieshouse.gov.uk/en_output.html"
PSC_URL = "http://download.companieshouse.gov.uk/en_pscdata.html"

KINDS = {
    "individual-person-with-significant-control": "Person",
    "corporate-entity-person-with-significant-control": "Company",
    "legal-person-person-with-significant-control": "Organization",
    "super-secure-person-with-significant-control": "",
    "persons-with-significant-control-statement": "",
    "exemptions": "",
}


def company_id(context: Zavod, company_nr):
    return f"{context.prefix}-{company_nr}"


@cache
def parse_date(text):
    if text is None or not len(text):
        return None
    return datetime.strptime(text, "%d/%m/%Y").date()


@cache
def clean_sector(text):
    sectors = text.split(" - ", 1)
    if len(sectors) > 1:
        return sectors[-1]


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
    context.log.info("Loading: %s" % data_path)
    for idx, row in enumerate(read_base_data_csv(data_path)):
        if idx > 0 and idx % 10000 == 0:
            context.log.info("Companies: %d..." % idx)
        company_nr = row.pop("CompanyNumber")
        entity = context.make("Company")
        entity.id = company_id(context, company_nr)
        entity.add("name", row.pop("CompanyName"))
        entity.add("registrationNumber", company_nr)
        entity.add("status", row.pop("CompanyStatus"))
        entity.add("legalForm", row.pop("CompanyCategory"))
        entity.add("country", row.pop("CountryOfOrigin"))
        entity.add("jurisdiction", "gb")
        # entity.add("sourceUrl", row.pop("URI"))

        for i in range(1, 5):
            sector = row.pop(f"SICCode.SicText_{i}")
            entity.add("sector", clean_sector(sector))
        inc_date = parse_date(row.pop("IncorporationDate"))
        entity.add("incorporationDate", inc_date)
        dis_date = parse_date(row.pop("DissolutionDate"))
        entity.add("dissolutionDate", dis_date)

        for i in range(1, 11):
            row.pop(f"PreviousName_{i}.CONDATE")
            entity.add("previousName", row.pop(f"PreviousName_{i}.CompanyName"))

        country = row.pop("RegAddress.Country")
        country_code = None
        if not len(country.strip()):
            country_code = "gb"
        addr = make_address(
            context,
            street=row.pop("RegAddress.AddressLine1"),
            street2=row.pop("RegAddress.AddressLine2"),
            street3=row.pop("RegAddress.CareOf"),
            po_box=row.pop("RegAddress.POBox"),
            postal_code=row.pop("RegAddress.PostCode"),
            region=row.pop("RegAddress.County"),
            city=row.pop("RegAddress.PostTown"),
            country=country,
            country_code=country_code,
        )
        if addr.id is not None:
            entity.add("addressEntity", addr.id)
            yield addr

        # pprint(entity.to_dict())
        yield entity


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
            with zip.open(name, "r") as fh:
                fhtext = TextIOWrapper(fh)
                while line := fhtext.readline():
                    yield json.loads(line)


def parse_psc_data(context: Zavod):
    data_url = get_psc_data_url(context)
    if data_url is None:
        context.log.error("PSC data zip URL not found!")
        return
    data_path = context.fetch_resource("psc_data.zip", data_url)
    context.log.info("Loading: %s" % data_path)
    for idx, row in enumerate(read_psc_data(data_path)):
        if idx > 0 and idx % 10000 == 0:
            context.log.info("PSC statements: %d..." % idx)
        company_nr = row.pop("company_number", None)
        if company_nr is None:
            context.log.warning("No company number: %r" % row)
            continue
        data = row.pop("data")
        data.pop("etag", None)
        url = data.pop("links").pop("self")
        psc_id = url.rsplit("/", 1)[-1]
        kind = data.pop("kind")
        schema = KINDS.get(kind)
        if schema == "":
            continue
        if schema is None:
            pprint((kind, data))
            continue
        psc = context.make(schema)
        psc.id = context.make_slug("psc", company_nr, psc_id)
        psc.add("name", data.pop("name"))
        nationality = data.pop("nationality", None)
        if psc.schema.is_a("Person"):
            psc.add("nationality", nationality, quiet=True)
        else:
            psc.add("jurisdiction", nationality, quiet=True)
        psc.add("country", data.pop("country_of_residence", None))

        names = data.pop("name_elements", {})
        psc.add("firstName", names.pop("forename", None), quiet=True)
        psc.add("middleName", names.pop("middle_name", None), quiet=True)
        psc.add("lastName", names.pop("surname", None), quiet=True)
        psc.add("title", names.pop("title", None), quiet=True)

        dob = data.pop("date_of_birth", {})
        dob_year = dob.pop("year", None)
        dob_month = dob.pop("month", None)
        if dob_year and dob_month:
            psc.add("birthDate", f"{dob_year}-{dob_month:02d}")

        address = data.pop("address", {})
        addr = make_address(
            context,
            remarks=address.pop("premises", None),
            street=address.pop("address_line_1", None),
            street2=address.pop("address_line_2", None),
            street3=address.pop("care_of", None),
            po_box=address.pop("po_box", None),
            postal_code=address.pop("postal_code", None),
            region=address.pop("region", None),
            city=address.pop("locality", None),
            country=address.pop("country", None),
        )
        if addr.id is not None:
            psc.add("addressEntity", addr.id)
            yield addr

        ident = data.pop("identification", {})
        reg_nr = ident.pop("registration_number", None)
        psc.add("registrationNumber", reg_nr, quiet=True)
        psc.add("legalForm", ident.pop("legal_form", None), quiet=True)
        psc.add("legalForm", ident.pop("legal_authority", None), quiet=True)
        psc.add("jurisdiction", ident.pop("country_registered", None), quiet=True)
        psc.add("jurisdiction", ident.pop("place_registered", None), quiet=True)
        # if len(ident):
        #     pprint(ident)

        link = context.make("Ownership")
        link.id = context.make_slug("stmt", company_nr, psc_id)
        link.add("owner", psc.id)
        link.add("asset", company_id(context, company_nr))
        link.add("modifiedAt", data.pop("notified_on"))
        link.add("endDate", data.pop("ceased_on", None))

        for nature in data.pop("natures_of_control"):
            nature = nature.replace("-", " ").capitalize()
            link.add("role", nature)

        if len(data):
            pprint(data)
        # pprint(link.to_dict())
        yield psc
        yield link


def process_base_data(context: Zavod):
    out_path = context.get_resource_path("base_data.json")
    with open(out_path, "wb") as fh:
        for entity in parse_base_data(context):
            write_entity(fh, entity)


def process_psc_data(context: Zavod):
    out_path = context.get_resource_path("psc_data.json")
    with open(out_path, "wb") as fh:
        for entity in parse_psc_data(context):
            write_entity(fh, entity)


def process_all(context):
    with ThreadPoolExecutor(max_workers=3) as pool:
        base_fut = pool.submit(process_base_data, context)
        psc_fut = pool.submit(process_psc_data, context)
        wait((base_fut, psc_fut))
        base_fut.result()
        psc_fut.result()


if __name__ == "__main__":
    with init_context("gb_coh_psc", "gb-coh") as context:
        process_all(context)
