from datetime import datetime, timedelta
from typing import Optional
import copy
import csv
import pytz

from fastapi import HTTPException

from labbot.module_loader import ModuleLoader

ETC = pytz.timezone('America/New_York')
module_config = {'client_key': '000000'}

label_queue = []

loader = ModuleLoader()

def register_module(config):
    # Override defaults if present 
    module_config.update(config)

    # Return
    return loader

label_model = {
    "type": "modal",
    "title": {
        "type": "plain_text",
        "text": ":label: Label printer",
        "emoji": True
    },
    "submit": {
        "type": "plain_text",
        "text": "Print",
        "emoji": True
    },
    "close": {
        "type": "plain_text",
        "text": "Cancel",
        "emoji": True
    },
    "callback_id": "label_print_view_submit",
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Metadata",
                "emoji": True
            }
        },
        {
            "type": "input",
            "element": {
                "type": "plain_text_input",
                "action_id": "initials-field"
            },
            "label": {
                "type": "plain_text",
                "text": "Your initials",
                "emoji": True
            }
        },
        {
            "type": "input",
            "element": {
                "type": "datepicker",
                "initial_value": "1990-04-28",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select a date",
                    "emoji": True
                },
                "action_id": "date-field"
            },
            "label": {
                "type": "plain_text",
                "text": "Date",
                "emoji": True
            }
        },
        {
            "type": "input",
            "element": {
                "type": "number_input",
                "is_decimal_allowed": False,
                "action_id": "num_copies-field",
                "initial_value": "3",
                "min_value": "1",
                "max_value": "10"
            },
            "label": {
                "type": "plain_text",
                "text": "# copies",
                "emoji": True
            }
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Details",
                "emoji": True
            }
        },
        {
            "type": "input",
            "element": {
                "type": "static_select",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select a label type",
                    "emoji": True
                },
                "options": [
                    {
                        "text": {
                            "type": "plain_text",
                            "text": "Bacterial stocking label",
                            "emoji": True
                        },
                        "value": "bacterial_stock"
                    },
                    {
                        "text": {
                            "type": "plain_text",
                            "text": "Cell-line stocking label",
                            "emoji": True
                        },
                        "value": "virus_stock"
                    },
                    {
                        "text": {
                            "type": "plain_text",
                            "text": "Virus stocking label",
                            "emoji": True
                        },
                        "value": "virus_stock"
                    },
                    {
                        "text": {
                            "type": "plain_text",
                            "text": "Custom label",
                            "emoji": True
                        },
                        "value": "custom"
                    }
                ],
                "action_id": "label_type-field"
            },
            "label": {
                "type": "plain_text",
                "text": "Label type",
                "emoji": True
            }
        },
        {
            "type": "input",
            "element": {
                "type": "plain_text_input",
                "multiline": True,
                "action_id": "labels-field",
                "placeholder": {
                    "type": "plain_text",
                    "text": "pKG_number, description",
                    "emoji": True
                }
            },
            "label": {
                "type": "plain_text",
                "text": "Labels (as CSV)",
                "emoji": True
            }
        }
    ]
}

def build_modal_view(*, text:Optional[str]=None, box_placeholder:Optional[str]=None):
    view_copy = copy.deepcopy(label_model)
    if box_placeholder is not None:
        view_copy['blocks'][6]['element']['placeholder']['text'] = box_placeholder
    if text is not None:
        view_copy['title']['text'] += '...'
        view_copy['blocks'].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":label: _{text}_"
            }
        })
    return view_copy

@loader.slack.shortcut("print_labels")
def main_tracker(ack, shortcut, client):
    """
    Handles when a user requests to print labels
    """
    ack()

    now_dt = datetime.now(ETC)

    # Set the default label date to today
    view_model = build_modal_view()
    view_model["blocks"][3]["element"]["initial_date"] = now_dt.strftime('%Y-%m-%d')

    # Open the view
    client.views_open(
        trigger_id = shortcut['trigger_id'],
        view=view_model
    )

@loader.slack.view('label_print_view_submit')
def handle_form_submission(ack, body, client, view):
    """
    Handles what happens when the label printer gets submitted
    """

    # Perform validation on inputs, e.g. check that the label CSV is well-formed
    labels = [row for row in csv.reader(view['state']['values']['labels-field'].split('\n'))]

    label_type = view['state']['values']['label_type-field']
    date = view['state']['values']['date-field']
    initials = view['state']['values']['initials-field']

    errors = {}

    try:
        n_copies = int(view['state']['values']['num_copies-field'])
        if n_copies <= 0:
            errors['num_copies-field'] = 'Number of copies must be a positive integer!'
    except ValueError:
        errors['num_copies-field'] = 'Number of copies must be a positive integer!'

    converted_labels = []
    if label_type == 'bacterial_stock':
        if not all([len(x) == 2 for x in labels]):
            errors["labels-field"] = "Input is not a two-column (pKG number, name) CSV!"
        # Try to convert all to int
        converted_labels = []
        for label in labels:
            try:
                pKG_num = int(label[0])
                converted_labels.append((
                    f'pKG{pKG_num}',
                    label[1],
                    f'{date} {initials}',
                    str(pKG_num)
                ))
            except ValueError:
                errors["labels-field"] = f"Row {label} has invalid pKG number! This should be an integer!"
                break
        labels = converted_labels
    elif label_type == 'cell_line_stock':
        if not all([len(x) == 3 for x in labels]):
            errors["labels-field"] = "Input is not a three-column (circle_label, main_label, description) CSV!"
        converted_labels.append((
            label[1],
            label[2],
            f'{date} {initials}',
            label[0]
        ))
    elif label_type == 'virus_stock':
        if not all([len(x) == 4 for x in labels]):
            errors["labels-field"] = "Input is not a four-column (circle_label, main_label, description, volume_uL) CSV!"
        converted_labels.append((
            f'{label[1]} ({label[3]} uL)',
            label[2],
            f'{date} {initials}',
            label[0]
        ))
    elif label_type == 'custom':
        if not all([len(x) == 3 for x in labels]):
            errors["labels-field"] = "Input is not a three-column (circle_label, line1, line2) CSV!"
        converted_labels.append((
            label[1],
            label[2],
            f'{date} {initials}',
            label[0]
        ))
    else:
        errors["label_type-field"] = "Unexpected label type!"
    if len(errors) > 0:
        ack(response_action="errors", errors=errors)
        return
    
    # Add to queue
    label_queue.append({
        'view_id': view.id,
        'label_count': n_copies,
        'labels': converted_labels
    })

    # Compute this 
    ack(response_action='update', view=build_modal_view(text="Labels queued..."))

@loader.fastapi.post("/labels/dequeue")
def dequeue_labels(token: str):
    if (token != module_config['token']):
        raise HTTPException(status_code=401, detail="Invalid auth token")

    try:
        labels = label_queue.pop(0)
        module_config['slack_client'].views_update(
            view_id = labels['view_id'],
            view=build_modal_view(text="Sent to label client...")
        )
        return labels
    except IndexError:
        return {}

@loader.fastapi.post("/labels/update_status")
def update_label_status(token: str, vid: int, status: str):
    if (token != module_config['token']):
        raise HTTPException(status_code=401, detail="Invalid auth token")
    
    module_config["slack_client"].views_update(
        view_id = vid,
        view=build_modal_view(text=f"{status}...")
    )