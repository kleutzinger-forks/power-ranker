from datetime import datetime
import json
from urllib.error import URLError

from graphqlclient import GraphQLClient
import gspread

import queries
from datamodels import *

with open('banned-tournament-slugs.txt', 'r') as f:
  slugs = f.readlines()
  slugs = [slug.strip() for slug in slugs]
  BANNED_TOURNEY_SLUGS = set(slugs) - {''}


def collect_user_ids_from_file():
  """Reads through a text file and compiles a dictionary of user_id -> player_name."""

  with open('user-ids.txt', 'r') as file:
    delimiter = '---'
    for line in file:
      if line.startswith('#'):
        continue
      # Get player name
      name_idx = line.index(delimiter)
      player_name = line[:name_idx]
      player_name, user_slug = line.split(delimiter)
      player_name = player_name.strip() 
      user_slug = user_slug.strip()
      if 'start.gg' in user_slug:
        user_slug = user_slug.split('/')[-1]
      # Get user id
      player_data = json.loads(execute_query(queries.get_player_id_from_player_slug, {"slug": user_slug}))['data']
      user_id = player_data.get("user").get("id")
      user_dict[user_id] = player_name


def execute_query(query, variables):
  """Executes GraphQL queries. Cycles through multiple tokens to avoid request limits."""

  global client_idx
  global clients

  if client_idx == len(clients):
    client_idx = 0

  result = clients[client_idx].execute(query, variables)
  
  client_idx += 1
  
  return result


def write_tourney_names_to_files(tournies):
  """Writes tourney names/slugs with dates to text files.
  Allows for a simple overview summary of tournaments.
  """
  i = 1
  with open('tourney_names.txt', 'w') as names, open('tourney_slugs.txt', 'w') as slugs:
    
    for tourney in tournies.values():
      notable_entries = ""
      if tourney.notable_entries:
        notable_entries = "--- " + ", ".join(tourney.notable_entries)
      url = 'https://start.gg/' + tourney.slug
      names.write(f'{tourney.name} --- {tourney.start_time.strftime("%m/%d")} --- {tourney.city}, {tourney.state} --- {url} {notable_entries}\n')
      slugs.write(f'{tourney.start_time} --- {tourney.slug} --- {tourney.city}, {tourney.state} {notable_entries}\n')
      
      i = i + 1


def write_removed_events_to_files(removed_events):
  """Writes tourney names/slugs with dates to text files.
  Allows for a simple overview summary of tournaments.
  """
  i = 1
  with open('removed_events.txt', 'w') as file:
    
    for event in removed_events:
      tourney = event.tourney
      file.write(f'{i}.) {tourney.start_time} --- Tourney: {tourney.name} --- Event: {event.name} --- {tourney.city}, {tourney.state}\n')
      
      i = i + 1


# def collect_tournies_for_users():
#   """Gathers a collection of tournaments and associated events for a user in a given season."""

#   tourney_dict = dict()
#   out_of_bounds_ctr = 0

#   # Keywords that should help exclude non-viable events
#   filter_names = {'doubles', 'teams', 'double', 'team'}
  
#   for user_id, player_name in user_dict.items():
#     print("Processing " + player_name + "'s tournaments...")
#     query_variables = {"userId": user_id}

#     result = execute_query(queries.get_events_by_user, query_variables)
#     res_data = json.loads(result)
#     if 'errors' in res_data:
#         print('Error:')
#         print(res_data['errors'])

#     for event_json in res_data['data']['user']['events']['nodes']:
#       cut_off_date_start = datetime(2022, 11, 1)
#       cut_off_date_end = datetime(2023, 5, 6)
      
#       tourney = Tournament(event_json['tournament'])
#       event = Event(event_json)
#       event.tourney = tourney
#       tourney.events.append(event)

#       # Validate PR eligibility
#       if tourney.is_online:
#         removed_events.add(event)
#         continue
#       if event.is_teams_event:
#         removed_events.add(event)
#         continue

#       is_not_singles = 1 in [name in event.name.lower() for name in filter_names]
#       if is_not_singles:
#         removed_events.add(event)
#         continue

#       if tourney.start_time < cut_off_date_start or tourney.start_time > cut_off_date_end:
#         # If three consecutive tournaments being processed is outside of the season's window,
#         # we can feel confident that the remaining tournaments to process are also out of bounds
#         out_of_bounds_ctr += 1
#         if out_of_bounds_ctr == 3:
#           break
#         continue
#       out_of_bounds_ctr = 0

#       gamerTag = res_data['data']['user']['player']['gamerTag']

#       event_dict[event.slug] = event

#       # If tournament is out of state, keep track of who attended from Kentucky
#       # if tourney.state != "KY":
#       #   if user_id in user_stats:
#       #     user_stats[user_id].all_tournies.append(tourney)
#       #   else:
#       #     user = User()
#       #     user.user_id = user_id
#       #     user.all_tournies.append(tourney)
#       #     user.gamer_tag = gamerTag
#       #     user_stats[user_id] = user

#       #   if tourney.slug in tourney_dict:
#       #     tourney_dict[tourney.slug].notable_entries.append(gamerTag)
#       #   else:
#       #     tourney.notable_entries.append(gamerTag)
#       #     tourney_dict[tourney.slug] = tourney
#       # else:
#       tourney_dict[tourney.slug] = tourney

#       if user_id in user_stats:
#         user_stats[user_id].all_tournies.append(tourney)
#         user_stats[user_id].ky_tournies.append(tourney)
#       else:
#         user = User()
#         user.user_id = user_id
#         user.all_tournies.append(tourney)
#         user.ky_tournies.append(tourney)
#         user.gamer_tag = gamerTag
#         user_stats[user_id] = user
        
#   return tourney_dict


def collect_tournies_for_users_last_season():
  """Gathers a collection of tournaments and associated events for a user in a given season."""

  tourney_dict = dict()
  out_of_bounds_ctr = 0
  
  for user_id, player_name in user_dict.items():
    print("Processing " + player_name + "'s tournaments...")
    query_variables = {"userId": user_id}

    result = execute_query(queries.get_tournies_by_user, query_variables)
    res_data = json.loads(result)
    if 'errors' in res_data:
        print('Error:')
        print(res_data['errors'])

    for tourney_json in res_data['data']['user']['tournaments']['nodes']:
      season_window_found = False
      cut_off_date_start = datetime(2022, 11, 1)
      cut_off_date_end = datetime(2023, 5, 7)
      
      tourney = Tournament(tourney_json)
      
      if tourney.is_online:
        continue

      if tourney.slug in BANNED_TOURNEY_SLUGS:
        print(f"found {tourney.slug} in banned tourney slugs")
        breakpoint()
        continue

      if tourney.start_time < cut_off_date_start or tourney.start_time > cut_off_date_end:
        # If three consecutive tournaments being processed is outside of the season's window,
        # we can feel confident that the remaining tournaments to process are also out of bounds
        if season_window_found:
          out_of_bounds_ctr += 1
          if out_of_bounds_ctr == 3:
            break
          continue
      else: # Within season window
        season_window_found = True
        out_of_bounds_ctr = 0

        tourney_dict[tourney.slug] = tourney
        user_to_tournies[user_id] = tourney.slug

  return tourney_dict


def set_events(tournies):
  """Queries events per tournaments. Attempts to filter out non-Singles events.
  Adds results to collection.
  """
  for tourney_slug, tourney_obj in tournies.items():
    print(f'\n{tourney_obj.name}')
    query_variables = {"slug": tourney_slug}
    result = execute_query(queries.get_events_by_tournament, query_variables)
    res_data = json.loads(result)
    if 'errors' in res_data:
        print('Error:')
        print(res_data['errors'])

    for event_json in res_data['data']['tournament']['events']:
      event = Event(event_json)
      print(f'---{event.name}')

      # Filter out events that are most likely not Singles events
      if (is_event_eligible(event)):
         tournies[tourney_slug].events.append(event)
      else:
        remove_event(event, tourney_obj)
        continue
      
  print('#########################################') 
  temp_dict = tournies.copy()
  for tourney_slug, tourney_obj in temp_dict.items():
    if tourney_obj.events == []:
      print(f'Removing  {tourney_obj.name}\n')
      tournies.pop(tourney_slug)


def is_event_eligible(event):
  """Checks for various conditions that would make an Event ineligible for PR."""
  
  is_eligible = True

  filter_names = {'doubles', 'double', 'team', 'teams'}
  is_not_singles = 1 in [name in event.name.lower() for name in filter_names]
  if is_not_singles:
    is_eligible = False
  
  if event.is_teams_event:
    is_eligible = False
  
  return is_eligible


def remove_event(event, tourney):
  """Removes event from collection."""

  print(f'Removing event:  {tourney.name} -- {event.name}')
  removed_events.add(event)


def write_user_stats_to_file(user_stats):
  """Writes user stats to file."""

  with open('user_stats.txt', 'w') as file:
    for user in user_stats.values():
      file.write(f'{user.gamer_tag} --- All tournies: {len(user.all_tournies)} --- KY events: {len(user.ky_tournies)}\n')


def init_clients():
  """Retrieves oauth tokens from a text file."""
  
  api_version = 'alpha'
  clients = []
  with open('tokens.txt', 'r') as file:
    for token in file:
      token = token.strip()
      if not token:
        continue
      client = GraphQLClient('https://api.start.gg/gql/' + api_version)
      client.inject_token('Bearer ' + token.strip())
      clients.append(client)

  return clients
      

def write_tourney_info_to_google_sheet(tournies):
  """Writes tourney data to a specified Google Sheet's Worksheet."""

  # gspread_client = gspread.service_account(filename='service_account.json')
  # sh = gspread_client.open("Test Sheet")
  # ws = sh.worksheet("ayo")
  
  row_num = 1
  rows = []

  for tourney in tournies.values():
    row = []
    row.append(str(row_num))
    row.append(tourney.name)
    row.append(tourney.start_time.strftime("%m/%d"))
    entrants = get_entrants(tourney)
    row.append(entrants)
    row = add_blank_fields_to_row(row, 16)
    row.append(", ".join(tourney.notable_entries))
    row.append(f'https://start.gg/{tourney.slug}/details')

    rows.append(row)

    row_num += 1

  # ws.update('A1', rows)
  print(row)
  print('hi')


def add_blank_fields_to_row(row, num_fields):
  """Adds the provided number of empty fields to a row."""

  for i in range(num_fields):
    row.append('')
  
  return row


def get_entrants(tourney):
  '''Fetches the likely number of entrants for a Singles event. 
  Takes the highest entrant count from all the (filtered) entrants a tourney has.
  If a tournament has multiple eligible events, this function will most likely return incorrect results.
  '''
  entrants = 0
  for event in tourney.events:
    if event.num_entrants > entrants:
      entrants = event.num_entrants
  
  if entrants == 0:
    entrants = 'Error'
  else:
    entrants = str(entrants)

  return entrants


client_idx = 0
current_token_index = 0
request_count = 0
clients = init_clients()

request_threshold = 79

##### Collections #####
user_to_tournies = dict()   #user_id -> tourney_slug
user_to_events = dict()     #user_id -> event_slug
user_to_gamer_tag = dict()  #user_id -> gamer_tag
user_dict = dict()          #user_id -> User object
user_stats = dict()

tourney_to_events = dict()  #tourney_slug -> event slug
event_dict = dict()         #event_slug -> Event object
removed_events = set()      #event_slug
removed_tournies = set()    #tourney_slug
##### End Collections #####

collect_user_ids_from_file()
# Sort results chronologically from earliest in the season to latest
tournies = dict(sorted(collect_tournies_for_users_last_season().items(), key=lambda kvp: kvp[1].start_time))

set_events(tournies)
write_tourney_names_to_files(tournies)
write_user_stats_to_file(user_stats)
write_tourney_info_to_google_sheet(tournies)
#write_removed_events_to_files(removed_events)


# TODO: Add all_events_removed_from_tourney idea
print('Process is complete.')
