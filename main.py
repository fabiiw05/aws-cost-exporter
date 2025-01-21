#!/usr/bin/python
# -*- coding:utf-8 -*-
# Filename: main.py

import argparse
import logging
import os
import signal
import sys
import time

from envyaml import EnvYAML
from prometheus_client import start_http_server

from app.exporter import MetricExporter


def handle_sigint(sig, frame):
    exit()


def get_configs():
    parser = argparse.ArgumentParser(description="AWS Cost Exporter, exposing AWS cost data as Prometheus metrics.")
    parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="The config file (exporter_config.yaml) for the exporter",
    )
    args = parser.parse_args()

    if not os.path.exists(args.config):
        logging.error("AWS Cost Exporter config file does not exist, or it is not a file!")
        sys.exit(1)

    config = EnvYAML(args.config)
    return config


def validate_configs(config):

    valid_metric_types = [
        "AmortizedCost",
        "BlendedCost",
        "NetAmortizedCost",
        "NetUnblendedCost",
        "NormalizedUsageAmount",
        "UnblendedCost",
        "UsageQuantity",
    ]

    if len(config["target_aws_accounts"]) == 0:
        logging.error("There should be at least one target AWS account defined in the config!")
        sys.exit(1)

    labels = config["target_aws_accounts"][0].keys()

    if "Publisher" not in labels:
        logging.error("Publisher is a mandatory key in target_aws_accounts!")
        sys.exit(1)

    for i in range(1, len(config["target_aws_accounts"])):
        if labels != config["target_aws_accounts"][i].keys():
            logging.error("All the target AWS accounts should have the same set of keys (labels)!")
            sys.exit(1)

    for config_metric in config["metrics"]:
        group_label_names = set()

        if config_metric["group_by"]["enabled"]:
            if len(config_metric["group_by"]["groups"]) < 1 or len(config_metric["group_by"]["groups"]) > 2:
                logging.error("If group_by is enabled, there should be at least one group, and at most two groups!")
                sys.exit(1)

            for group in config_metric["group_by"]["groups"]:
                if group["label_name"] in group_label_names:
                    logging.error("Group label names should be unique!")
                    sys.exit(1)
                else:
                    group_label_names.add(group["label_name"])

            if group_label_names & set(labels):
                logging.error("Some label names in group_by are the same as AWS account labels!")
                sys.exit(1)

        # Validate metric_type
        if config_metric["metric_type"] not in valid_metric_types:
            logging.error(
                f"Invalid metric_type: {config_metric['metric_type']}. It must be one of {', '.join(valid_metric_types)}."
            )
            sys.exit(1)

        # Validate tag_filters if present
        if "tag_filters" in config_metric:
            tag_filters = config_metric["tag_filters"]
            if not isinstance(tag_filters, list):
                logging.error("tag_filters should be a list, check `exporter_config.yaml` as an example.")
                sys.exit(1)
            for tag_filter in tag_filters:
                if not isinstance(tag_filter["tag_values"], list):
                    logging.error(f"Values for tag `{tag_filter['tag_key']}` should be a list, check `exporter_config.yaml` as an example.")
                    sys.exit(1)

    # No need to repeat the validation loops; they have been consolidated above.


def main(config):
    metric_exporters = []
    for config_metric in config["metrics"]:
        metric = MetricExporter(
            polling_interval_seconds=config["polling_interval_seconds"],
            aws_access_key=config["aws_access_key"],
            aws_access_secret=config["aws_access_secret"],
            aws_assumed_role_name=config["aws_assumed_role_name"],
            targets=config["target_aws_accounts"],
            metric_name=config_metric["metric_name"],
            group_by=config_metric["group_by"],
            metric_type=config_metric["metric_type"],
        )
        metric_exporters.append(metric)

    start_http_server(config["exporter_port"])
    while True:
        for exporter in metric_exporters:
            exporter.run_metrics()
        time.sleep(config["polling_interval_seconds"])


if __name__ == "__main__":
    logger_format = "%(asctime)-15s %(levelname)-8s %(message)s"
    logging.basicConfig(level=logging.INFO, format=logger_format)
    signal.signal(signal.SIGINT, handle_sigint)
    config = get_configs()
    validate_configs(config)
    main(config)
