-- first migration
-- depends: 

create table issue
(
	id integer
		constraint issue_pk
			primary key autoincrement,
	uuid text not null,
	at datetime not null,
	num_stories int not null,
	period text not null,
	meta text not null
);

create unique index issue_uuid_uindex
	on issue (uuid);

create index issue_period_index
	on issue (period);

create table issue_format
(
    issue_id integer not null
        references issue,
    file_name text not null,
    file_size integer not null,
    mimetype text not null
);

create table hn_best_story
(
	story_id integer not null,
	day date not null
);

create unique index hn_best_story_story_id_uindex
	on hn_best_story (story_id);

create table story_issue
(
	issue_id integer not null
		references issue,
	story_id integer not null
		constraint story_issue_hn_best_story_story_id_fk
			references hn_best_story (story_id)
);
