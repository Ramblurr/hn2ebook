-- first migration
-- depends: 

create table generated_book
(
	id integer
		constraint generated_book_pk
			primary key autoincrement,
	uuid text not null,
	at datetime not null,
	num_stories int not null,
	period text not null,
	meta text not null
);

create unique index generated_book_uuid_uindex
	on generated_book (uuid);

create index generated_book_period_index
	on generated_book (period);

create table generated_book_format
(
    book_id integer not null
        references generated_book,
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

create table story_book
(
	book_id integer not null
		references generated_book,
	story_id integer not null
		constraint story_book_hn_best_story_story_id_fk
			references hn_best_story (story_id)
);
