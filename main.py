from datetime import datetime
import json
from urllib.error import URLError

from graphqlclient import GraphQLClient
#import gspread

import queries
from datamodels import *


def get_tokens():
  """Retrieves oauth tokens from a text file."""
  
  tokens = []
  with open('tokens.txt', 'r') as file:
    for token in file:
      tokens.append(token.strip())

  return tokens


def reset_client():
  """Before reaching request limit, inject a fresh auth token to reset request count."""
  
  global current_token_index
  global request_count 
  request_count = 0

  client.inject_token('Bearer ' + auth_tokens[current_token_index])
  if current_token_index == len(auth_tokens) - 1:
    current_token_index = 0
  else:
    current_token_index += 1


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
      
      # Get user id
      id_idx = name_idx + 3
      user_id = line[id_idx:].strip()
      user_dict[user_id] = player_name


# Currently deprecated
def set_tournaments():
  """Runs a tournament query for each user that was collected.
  Returns a dictonary of tourney_slug -> TourneyObj.
  """
  tourney_dict = dict()
  for user_id, player_name in user_dict.items():
    print("Processing " + player_name + "'s tournaments...")
    query_variables = {"userId": user_id}

    result = execute_query(queries.get_tournies_by_user, query_variables)
    res_data = json.loads(result)
    if 'errors' in res_data:
        print('Error:')
        print(res_data['errors'])

    for tourney_json in res_data['data']['user']['tournaments']['nodes']:
      cut_off_date_start = datetime(2022, 10, 1)
      cut_off_date_end = datetime(2022, 12, 31)
      
      tourney = Tournament(tourney_json)
    
      str_date = tourney.start_time.strftime('%m-%d-%Y')
      
      if tourney.start_time >= cut_off_date_start and tourney.start_time <= cut_off_date_end:
        if tourney.is_online:
          continue
        print(tourney.name + '\t' + str_date)
        tourney_dict[tourney.slug] = tourney
      elif tourney.start_time < cut_off_date_start:
        print('Tournament outside of season window --- ' + tourney.name + '\t' + str_date)
        break
  
  return tourney_dict


def execute_query(query, variables):
  """Executes GraphQL queries. Implements a retry system if a bad connection occurs."""
  
  try_attempt_ctr = 1
  total_attempts = 3
  global request_count

  while try_attempt_ctr <= total_attempts:
    if request_count == request_threshold:
      reset_client()
    try:
      print(f'{auth_tokens[current_token_index]}\n')
      request_count += 1
      result = client.execute(query, variables)
      return result
    except URLError:
      try_attempt_ctr += 1

  raise URLError(f'Max number of attempts ({total_attempts}) exceeded.')


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
      names.write(f'{i}) {tourney.name} --- {tourney.start_time.strftime("%m/%d")} --- {tourney.city}, {tourney.state} --- {url} {notable_entries}\n')
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

def collect_tournies_for_users():
  """Gathers a collection of tournaments and associated events for a user in a given season."""

  tourney_dict = dict()
  out_of_bounds_ctr = 0

  # Keywords that should help exclude non-viable events
  filter_names = {'squad strike', 'crew battle', 'redemption', 'ladder', 'doubles', 'amateur'}
  
  for user_id, player_name in user_dict.items():
    print("Processing " + player_name + "'s tournaments...")
    query_variables = {"userId": user_id}

    result = execute_query(queries.get_events_by_user, query_variables)
    res_data = json.loads(result)
    if 'errors' in res_data:
        print('Error:')
        print(res_data['errors'])

    for event_json in res_data['data']['user']['events']['nodes']:
      cut_off_date_start = datetime(2023, 1, 1)
      cut_off_date_end = datetime(2023, 3, 31)
      
      tourney = Tournament(event_json['tournament'])
      event = Event(event_json)
      event.tourney = tourney
      tourney.events.append(event)

      # Validate PR eligibility
      if tourney.is_online:
        removed_events.add(event)
        continue
      if event.num_entrants < 8:
        removed_events.add(event)
        continue
      if event.is_teams_event:
        removed_events.add(event)
        continue

      is_not_singles = 1 in [name in event.name.lower() for name in filter_names]
      if is_not_singles:
        removed_events.add(event)
        continue

      if tourney.start_time < cut_off_date_start or tourney.start_time > cut_off_date_end:
        # If three consecutive tournaments being processed is outside of the season's window,
        # we can feel confident that the remaining tournaments to process are also out of bounds
        out_of_bounds_ctr += 1
        if out_of_bounds_ctr == 3:
          break
        continue
      out_of_bounds_ctr = 0

      gamerTag = res_data['data']['user']['player']['gamerTag']

      event_dict[event.slug] = event

      # If tournament is out of state, keep track of who attended from Kentucky
      if tourney.state != "KY":
        if user_id in user_stats:
          user_stats[user_id].all_tournies.append(tourney)
        else:
          user = User()
          user.user_id = user_id
          user.all_tournies.append(tourney)
          user.gamer_tag = gamerTag
          user_stats[user_id] = user

        if tourney.slug in tourney_dict:
          tourney_dict[tourney.slug].notable_entries.append(gamerTag)
        else:
          tourney.notable_entries.append(gamerTag)
          tourney_dict[tourney.slug] = tourney
      else:
        tourney_dict[tourney.slug] = tourney

        if user_id in user_stats:
          user_stats[user_id].all_tournies.append(tourney)
          user_stats[user_id].ky_tournies.append(tourney)
        else:
          user = User()
          user.user_id = user_id
          user.all_tournies.append(tourney)
          user.ky_tournies.append(tourney)
          user.gamer_tag = gamerTag
          user_stats[user_id] = user
        
  return tourney_dict

def collect_tournies_for_users_last_season():
  """Gathers a collection of tournaments and associated events for a user in a given season."""

  tourney_dict = dict()
  out_of_bounds_ctr = 0

  # Keywords that should help exclude non-viable events
  filter_names = {'squad strike', 'crew battle', 'redemption', 'ladder', 'doubles', 'amateur'}
  
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
      cut_off_date_start = datetime(2022, 9, 30)
      cut_off_date_end = datetime(2022, 12, 31)
      
      tourney = Tournament(tourney_json)

      if tourney.is_online:
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
  global client
  filter_names = {'squad strike', 'crew battle', 'redemption', 'ladder', 'doubles', 'amateur'}
  
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

      # Filter out events that are most likely not Singles events
      if event.is_teams_event:
        continue
      is_not_singles = 1 in [name in event.name.lower() for name in filter_names]
      if is_not_singles:
        continue
      if event.num_entrants < 12 and event.start_time < datetime(2022, 11, 14):
        removed_events.add(event)
        continue
      if event.num_entrants < 8 and event.start_time >= datetime(2022, 11, 14):
        removed_events.add(event)
        continue
      if event.is_teams_event:
        removed_events.add(event)
        continue
      
      tournies[tourney_slug].events.append(event)
      print(f'---{event.name}')

   
  print('#########################################') 
  temp_dict = tournies.copy()
  for tourney_slug, tourney_obj in temp_dict.items():
    if tourney_obj.events == []:
      print(f'Removing  {tourney_obj.name}\n')
      tournies.pop(tourney_slug)

def write_user_stats_to_file(user_stats):
  with open('user_stats.txt', 'w') as file:
    for user in user_stats.values():
      file.write(f'{user.gamer_tag} --- All tournies: {len(user.all_tournies)} --- KY events: {len(user.ky_tournies)}\n')


auth_tokens = get_tokens()
current_token_index = 0
api_version = 'alpha'
request_count = 0
client = GraphQLClient('https://api.start.gg/gql/' + api_version)
reset_client()
ultimate_id = '1386'


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

#gspread_client = gspread.service_account(filename='service_account.json')
#sh = gspread_client.open("Test Sheet")
#worksheet = sh.worksheet("ayo")

collect_user_ids_from_file()
# Sort results chronologically from earliest in the season to latest
tournies = dict(sorted(collect_tournies_for_users_last_season().items(), key=lambda kvp: kvp[1].start_time))

set_events(tournies)
write_tourney_names_to_files(tournies)
write_user_stats_to_file(user_stats)
#write_removed_events_to_files(removed_events)


# TODO: Add all_events_removed_from_tourney idea
print('Process is complete.')